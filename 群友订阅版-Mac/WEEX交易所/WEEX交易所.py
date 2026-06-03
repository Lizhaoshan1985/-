import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / '跟单.env'
STATE_PATH = ROOT / 'state.json'
LOG_PATH = ROOT / '跟单.log'

DEFAULT_SIGNAL_API_URL = 'http://147.124.215.90:9005/latest'
DEFAULT_LEVERAGE_REFRESH_SECONDS = 4 * 60 * 60
MAX_LEVERAGE_ENV_PREFIX = 'WEEX_MAX_LEVERAGE_'
MAX_LEVERAGE_BLOCK_START = '# 合约最大杠杆倍数：程序启动检查并每 4 小时自动更新'
MAX_LEVERAGE_BLOCK_END = '# 自动记录结束'

SYMBOL_MAP = {
    'ETH': 'ETHUSDT',
    'BTC': 'BTCUSDT',
    'TON': 'TONUSDT',
    'DOGE': 'DOGEUSDT',
    'SOL': 'SOLUSDT',
    'XRP': 'XRPUSDT',
    'BNB': 'BNBUSDT',
    'XAUT': 'XAUTUSDT',
}

PRICE_TICK = {
    'ETHUSDT': Decimal('0.01'),
    'BTCUSDT': Decimal('0.1'),
    'TONUSDT': Decimal('0.0001'),
    'DOGEUSDT': Decimal('0.00001'),
    'SOLUSDT': Decimal('0.001'),
    'XRPUSDT': Decimal('0.0001'),
    'BNBUSDT': Decimal('0.01'),
    'XAUTUSDT': Decimal('0.01'),
}

QTY_STEP = {
    'ETHUSDT': Decimal('0.0001'),
    'BTCUSDT': Decimal('0.0001'),
    'TONUSDT': Decimal('0.01'),
    'DOGEUSDT': Decimal('1'),
    'SOLUSDT': Decimal('0.01'),
    'XRPUSDT': Decimal('1'),
    'BNBUSDT': Decimal('0.001'),
    'XAUTUSDT': Decimal('0.001'),
}

MIN_QTY = {
    'ETHUSDT': Decimal('0.0001'),
    'BTCUSDT': Decimal('0.0001'),
    'TONUSDT': Decimal('0.01'),
    'DOGEUSDT': Decimal('1'),
    'SOLUSDT': Decimal('0.01'),
    'XRPUSDT': Decimal('1'),
    'BNBUSDT': Decimal('0.001'),
    'XAUTUSDT': Decimal('0.001'),
}

ENV = {}
TRADE_ENABLED = False
MARKET_RULE_CACHE = {'ts': 0, 'data': {}}


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def read_env():
    if not ENV_PATH.exists():
        raise RuntimeError('找不到 跟单.env')
    env = {}
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()
    return env


def validate_env(env):
    required = ['SUB_CODE']
    missing = [k for k in required if not env.get(k)]
    if missing:
        if 'SUB_CODE' in missing:
            raise RuntimeError('缺少注册码：请在 跟单.env 里填写 SUB_CODE 后重新启动')
        raise RuntimeError('跟单.env 未填完整: ' + ', '.join(missing))


def trade_env_ready(env):
    required = ['WEEX_API_KEY', 'WEEX_API_SECRET', 'WEEX_API_PASSPHRASE']
    missing = [k for k in required if not env.get(k)]
    if missing:
        return False, '未填写交易所 API：当前仅监听信号，不会自动下单'
    return True, 'WEEX 交易已启用'


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'active_trade': None,
        'last_signal_msg_id': 0,
        'traded_signal_msg_ids': [],
    }


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def as_decimal(value, default='0'):
    if value in (None, ''):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def quantize(symbol, value, is_qty=False):
    step = get_qty_step(symbol) if is_qty else PRICE_TICK.get(symbol, Decimal('0.0001'))
    return (Decimal(str(value)) / step).to_integral_value(rounding=ROUND_DOWN) * step


def resolve_symbol(asset):
    asset = str(asset or '').upper()
    return SYMBOL_MAP.get(asset) or f'{asset}USDT'


def _stringify_params(data):
    out = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = 'true' if v else 'false'
        else:
            out[k] = str(v)
    return out


def weex_request(method, path, params=None, body=None, signed=True):
    params = _stringify_params(params)
    query = urllib.parse.urlencode(params)
    ts = str(int(time.time() * 1000))
    base_url = (ENV.get('WEEX_BASE_URL') or 'https://api-contract.weex.com').rstrip('/')
    url = base_url + path
    if query:
        url += '?' + query
    headers = {'Content-Type': 'application/json'}
    body_text = ''
    data = None
    if body is not None:
        body_text = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
        data = body_text.encode()
    if signed:
        prehash = f'{ts}{method.upper()}{path}'
        if query:
            prehash += f'?{query}'
        prehash += body_text
        digest = hmac.new(ENV['WEEX_API_SECRET'].encode(), prehash.encode(), hashlib.sha256).digest()
        sig = base64.b64encode(digest).decode()
        headers.update({
            'ACCESS-KEY': ENV['WEEX_API_KEY'],
            'ACCESS-SIGN': sig,
            'ACCESS-PASSPHRASE': ENV['WEEX_API_PASSPHRASE'],
            'ACCESS-TIMESTAMP': ts,
        })
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        err_body = e.read().decode(errors='ignore')
        raise RuntimeError(f'WEEX HTTP {e.code} {method} {path} resp={err_body or e.reason}') from e


def fetch_latest_signal():
    url = DEFAULT_SIGNAL_API_URL
    req = urllib.request.Request(url, headers={'X-Sub-Code': ENV['SUB_CODE']}, method='GET')
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    if not data.get('ok'):
        raise RuntimeError(f'信号服务返回错误: {data}')
    return data.get('signal')


def fetch_collateral():
    rows = weex_request('GET', '/capi/v3/account/balance') or []
    total = Decimal('0')
    available = Decimal('0')
    for row in rows:
        if row.get('asset') != 'USDT':
            continue
        total += as_decimal(row.get('balance'))
        available += as_decimal(row.get('availableBalance'))
    return total, available


def write_env_leverages(rules):
    tracked = []
    for symbol, rule in (rules or {}).items():
        leverage = (rule or {}).get('max_leverage')
        if leverage:
            tracked.append((symbol, format_decimal(leverage), as_decimal((rule or {}).get('quote_volume'))))
    if not tracked:
        return

    lines = ENV_PATH.read_text(encoding='utf-8').splitlines() if ENV_PATH.exists() else []
    cleaned = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped == MAX_LEVERAGE_BLOCK_START:
            skip = True
            continue
        if stripped == MAX_LEVERAGE_BLOCK_END:
            skip = False
            continue
        if skip or stripped.startswith(MAX_LEVERAGE_ENV_PREFIX):
            continue
        cleaned.append(line)

    block = [
        '',
        MAX_LEVERAGE_BLOCK_START,
        *[
            f'{MAX_LEVERAGE_ENV_PREFIX}{symbol}={leverage}'
            for symbol, leverage, _ in sorted(tracked, key=lambda item: (-item[2], item[0]))
        ],
        MAX_LEVERAGE_BLOCK_END,
    ]
    insert_at = None
    for idx, line in enumerate(cleaned):
        if line.strip().startswith('WEEX_ORDER_USDT='):
            insert_at = idx + 1
            break
    if insert_at is None:
        cleaned.extend(block)
    else:
        cleaned[insert_at:insert_at] = block
    ENV_PATH.write_text('\n'.join(cleaned).rstrip() + '\n', encoding='utf-8')


def refresh_exchange_info(force=False):
    ttl = DEFAULT_LEVERAGE_REFRESH_SECONDS
    now = time.time()
    if not force and MARKET_RULE_CACHE['data'] and now - MARKET_RULE_CACHE['ts'] < ttl:
        return MARKET_RULE_CACHE['data']
    data = weex_request('GET', '/capi/v3/market/exchangeInfo', signed=False) or {}
    ticker_data = weex_request('GET', '/capi/v3/market/ticker/24hr', signed=False) or []
    ticker_rows = ticker_data.get('data') if isinstance(ticker_data, dict) else ticker_data
    if not isinstance(ticker_rows, list):
        ticker_rows = []
    quote_volumes = {}
    for row in ticker_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('symbol') or '').upper()
        if symbol:
            quote_volumes[symbol] = as_decimal(row.get('quoteVolume'))
    rows = data.get('symbols') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        rows = []
    rules = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('symbol') or '').upper()
        if not symbol:
            continue
        quantity_precision = row.get('quantityPrecision')
        qty_step = None
        if quantity_precision not in (None, ''):
            precision = int(quantity_precision)
            qty_step = Decimal(10) ** Decimal(-precision)
        rules[symbol] = {
            'max_leverage': as_decimal(row.get('maxLeverage')),
            'min_qty': as_decimal(row.get('minOrderSize')),
            'qty_step': qty_step,
            'quote_volume': quote_volumes.get(symbol, Decimal('0')),
        }
    if rules:
        MARKET_RULE_CACHE['data'] = rules
        MARKET_RULE_CACHE['ts'] = now
        write_env_leverages(rules)
    return MARKET_RULE_CACHE['data']


def get_market_rule(symbol):
    return refresh_exchange_info().get(symbol, {})


def get_qty_step(symbol):
    rule = get_market_rule(symbol)
    step = rule.get('qty_step') or QTY_STEP.get(symbol) or Decimal('0.0001')
    return Decimal(str(step))


def get_min_qty(symbol):
    rule = get_market_rule(symbol)
    qty = rule.get('min_qty') or MIN_QTY.get(symbol) or Decimal('0.0001')
    return Decimal(str(qty))


def resolve_leverage(symbol):
    raw = str(ENV.get('WEEX_LEVERAGE') or 'MAX').strip().upper()
    if raw and raw not in ('MAX', 'AUTO'):
        leverage = as_decimal(raw)
        if leverage > 0:
            return leverage
    leverage = get_market_rule(symbol).get('max_leverage')
    if not leverage:
        leverage = as_decimal(ENV.get(f'{MAX_LEVERAGE_ENV_PREFIX}{symbol}'))
    if not leverage:
        raise RuntimeError(f'无法从 WEEX 获取 {symbol} 最大杠杆')
    return leverage


def format_decimal(value):
    value = Decimal(str(value))
    return format(value.normalize(), 'f').rstrip('0').rstrip('.') if '.' in format(value.normalize(), 'f') else format(value.normalize(), 'f')


def update_leverage(symbol, leverage):
    margin_type = (ENV.get('WEEX_MARGIN_TYPE') or 'ISOLATED').strip().upper()
    leverage_text = format_decimal(leverage)
    body = {'symbol': symbol, 'marginType': margin_type}
    if margin_type == 'CROSSED':
        body['crossLeverage'] = leverage_text
    else:
        body['marginType'] = 'ISOLATED'
        body['isolatedLongLeverage'] = leverage_text
        body['isolatedShortLeverage'] = leverage_text
    try:
        weex_request('POST', '/capi/v3/account/leverage', body=body)
        log(f'已设置杠杆 | {symbol} {leverage_text}x {body["marginType"]}')
    except Exception as e:
        raise RuntimeError(f'设置 {symbol} 杠杆失败: {e}') from e


def get_last_price(symbol):
    ticker = weex_request(
        'GET',
        '/capi/v3/market/symbolPrice',
        {'symbol': symbol, 'priceType': 'MARK'},
        signed=False,
    )
    price = as_decimal((ticker or {}).get('price'))
    if price <= 0:
        raise RuntimeError(f'无法解析 WEEX 价格: {symbol}')
    return price


def fetch_positions(symbol=None):
    rows = weex_request('GET', '/capi/v3/account/position/allPosition') or []
    if symbol:
        rows = [row for row in rows if row.get('symbol') == symbol]
    return rows


def get_position(symbol):
    for row in fetch_positions(symbol):
        qty = as_decimal(row.get('size'))
        if qty == 0:
            continue
        side = str(row.get('side') or '').upper()
        open_value = as_decimal(row.get('openValue'))
        entry_price = open_value / abs(qty) if open_value > 0 and qty else as_decimal(row.get('entryPrice'))
        return {
            'qty': abs(qty),
            'side': side,
            'entry_price': entry_price,
            'unrealized_pnl': as_decimal(row.get('unrealizePnl')),
        }
    return {'qty': Decimal('0'), 'side': '', 'entry_price': Decimal('0'), 'unrealized_pnl': Decimal('0')}


def cancel_all_open_orders(symbol):
    try:
        weex_request('DELETE', '/capi/v3/allOpenOrders', {'symbol': symbol})
    except Exception as e:
        log(f'取消普通挂单失败: {e}')


def place_market_order(symbol, side, position_side, qty, reduce_only=False):
    body = {
        'symbol': symbol,
        'side': 'BUY' if side.lower() == 'buy' else 'SELL',
        'positionSide': position_side,
        'type': 'MARKET',
        'quantity': format_decimal(qty),
        'newClientOrderId': f'sub-{time.time_ns()}',
    }
    if reduce_only:
        body['reduceOnly'] = True
    return weex_request('POST', '/capi/v3/order', body=body)


def calc_signal_qty(symbol, entry, leverage):
    entry = Decimal(str(entry))
    margin_usdt = Decimal(ENV.get('WEEX_ORDER_USDT') or '20')
    notional = margin_usdt * Decimal(str(leverage))
    qty = quantize(symbol, notional / entry, is_qty=True)
    if qty < get_min_qty(symbol):
        return None
    return qty


def split_qty(symbol, qty, parts):
    if parts <= 1:
        return [qty]
    base = quantize(symbol, qty / Decimal(parts), is_qty=True)
    if base <= 0:
        return [qty]
    out = []
    used = Decimal('0')
    for idx in range(parts):
        piece = quantize(symbol, qty - used, is_qty=True) if idx == parts - 1 else base
        if piece > 0:
            out.append(piece)
            used += piece
    return out or [qty]


def signal_tp_quantities(symbol, qty, take_profits):
    if not take_profits:
        return []
    if len(take_profits) == 1:
        half = quantize(symbol, qty * Decimal('0.5'), is_qty=True)
        return [half if half > 0 else qty]
    first = quantize(symbol, qty * Decimal('0.5'), is_qty=True)
    if first <= 0:
        return [qty]
    second = quantize(symbol, qty - first, is_qty=True)
    return [first, second if second > 0 else qty - first]


def normalize_signal(signal):
    if not signal:
        return None
    asset = str(signal.get('symbol') or '').upper()
    side = str(signal.get('side') or '').upper()
    entry = signal.get('entry')
    if side not in ('LONG', 'SHORT') or entry is None:
        return None
    symbol = resolve_symbol(asset)
    leverage = resolve_leverage(symbol)
    qty = calc_signal_qty(symbol, Decimal(str(entry)), leverage)
    if qty is None:
        return None
    stop_loss = signal.get('stop_loss')
    take_profits = []
    for value in signal.get('take_profits') or signal.get('targets') or []:
        if value is not None:
            take_profits.append(Decimal(str(value)))
    return {
        'asset': asset,
        'symbol': symbol,
        'signal_side': side,
        'entry': Decimal(str(entry)),
        'qty': qty,
        'leverage': leverage,
        'stop_loss': Decimal(str(stop_loss)) if stop_loss is not None else None,
        'take_profits': take_profits,
        'msg_id': int(signal.get('msg_id') or 0),
        'ts': int(signal.get('ts') or 0),
    }


def close_position_market(active_trade, reason, state):
    symbol = active_trade['symbol']
    side = active_trade['side']
    qty = Decimal(str(active_trade['qty']))
    close_side = 'sell' if side == 'LONG' else 'buy'
    place_market_order(symbol, close_side, side, qty, reduce_only=True)
    log(f'{reason}，已市价平仓 | {symbol} {side} qty={qty}')
    state['active_trade'] = None
    save_state(state)


def manage_active_trade(state):
    active = state.get('active_trade')
    if not active:
        return
    symbol = active['symbol']
    pos = get_position(symbol)
    if pos['qty'] <= 0:
        log('仓位已无，清空状态')
        state['active_trade'] = None
        save_state(state)
        return
    active['qty'] = str(pos['qty'])
    active['side'] = pos['side']
    active['entry_price'] = str(pos['entry_price'])
    last_price = get_last_price(symbol)
    stop_loss = active.get('stop_loss')
    if stop_loss not in (None, ''):
        stop = Decimal(str(stop_loss))
        stop_hit = (active['side'] == 'LONG' and last_price <= stop) or (active['side'] == 'SHORT' and last_price >= stop)
        if stop_hit:
            return close_position_market(active, f'触发信号止损 SL={stop}', state)

    take_profits = [Decimal(str(x)) for x in active.get('take_profits') or [] if str(x)]
    tp_quantities = [Decimal(str(x)) for x in active.get('tp_quantities') or [] if str(x)]
    if len(tp_quantities) < len(take_profits):
        tp_quantities = signal_tp_quantities(symbol, pos['qty'], take_profits)
    tp_filled = list(active.get('tp_filled') or [False for _ in take_profits])
    changed = False
    for idx, tp in enumerate(take_profits):
        if idx < len(tp_filled) and tp_filled[idx]:
            continue
        hit = (active['side'] == 'LONG' and last_price >= tp) or (active['side'] == 'SHORT' and last_price <= tp)
        if not hit:
            continue
        tp_qty = tp_quantities[idx] if idx < len(tp_quantities) else pos['qty']
        close_side = 'sell' if active['side'] == 'LONG' else 'buy'
        place_market_order(symbol, close_side, active['side'], tp_qty, reduce_only=True)
        if idx >= len(tp_filled):
            tp_filled.extend([False] * (idx + 1 - len(tp_filled)))
        tp_filled[idx] = True
        changed = True
        log(f'触发信号止盈{idx + 1}，已市价减仓 | {symbol} {active["side"]} qty={tp_qty} | TP={tp}')
    active['tp_filled'] = tp_filled
    active['tp_quantities'] = [str(x) for x in tp_quantities]
    if take_profits and all(tp_filled[:len(take_profits)]):
        log('信号止盈全部完成，清空状态')
        state['active_trade'] = None
        save_state(state)
        return

    pnl_value = pos.get('unrealized_pnl') or Decimal('0')
    log(f"持仓正常 | {active['asset']} {'多' if active['side'] == 'LONG' else '空'} | 当前价={last_price} | 浮盈={pnl_value}U")
    if changed:
        state['active_trade'] = active
    save_state(state)


def maybe_open_from_signal(state, signal):
    if not TRADE_ENABLED:
        if signal:
            msg_id = int(signal.get('msg_id') or 0)
            if msg_id != int(state.get('last_seen_signal_msg_id') or 0):
                state['last_seen_signal_msg_id'] = msg_id
                save_state(state)
                log(f"收到信号，仅监听不交易 | 今日第{signal.get('daily_order_no') or '?'}单 | {signal.get('raw_text') or signal}")
        return

    sig = normalize_signal(signal)
    if not sig:
        return
    msg_id = sig['msg_id']
    traded_ids = state.get('traded_signal_msg_ids') or []
    if msg_id and msg_id in traded_ids:
        return
    if msg_id and msg_id == int(state.get('last_signal_msg_id') or 0):
        return
    if state.get('active_trade'):
        return

    symbol = sig['symbol']
    pos = get_position(symbol)
    if pos['qty'] > 0:
        log(f'已有 {symbol} 持仓，本次不下单')
        state['last_signal_msg_id'] = msg_id
        save_state(state)
        return

    cancel_all_open_orders(symbol)
    update_leverage(symbol, sig['leverage'])
    open_side = 'buy' if sig['signal_side'] == 'LONG' else 'sell'
    place_market_order(symbol, open_side, sig['signal_side'], sig['qty'])
    log(f"开仓: {sig['asset']} {sig['signal_side']} qty={sig['qty']} | 杠杆={format_decimal(sig['leverage'])}x | 本金={ENV.get('WEEX_ORDER_USDT') or '20'}U | 信号={msg_id}")
    time.sleep(2)
    pos = get_position(symbol)
    entry = pos['entry_price'] if pos['entry_price'] > 0 else sig['entry']
    stop_loss = quantize(symbol, sig['stop_loss']) if sig['stop_loss'] is not None else ''
    take_profits = [quantize(symbol, tp) for tp in (sig.get('take_profits') or [])[:2]]
    position_qty = pos['qty'] if pos['qty'] > 0 else sig['qty']
    tp_quantities = signal_tp_quantities(symbol, position_qty, take_profits)
    active = {
        'asset': sig['asset'],
        'symbol': symbol,
        'side': pos['side'] or sig['signal_side'],
        'entry_price': str(entry),
        'qty': str(pos['qty'] if pos['qty'] > 0 else sig['qty']),
        'leverage': str(sig['leverage']),
        'stop_loss': str(stop_loss),
        'take_profits': [str(tp) for tp in take_profits],
        'tp_quantities': [str(qty) for qty in tp_quantities],
        'tp_filled': [False for _ in take_profits],
        'msg_id': msg_id,
    }
    state['active_trade'] = active
    state['last_signal_msg_id'] = msg_id
    if msg_id:
        traded_ids.append(msg_id)
        state['traded_signal_msg_ids'] = traded_ids[-50:]
    save_state(state)


def main():
    global ENV, TRADE_ENABLED
    ENV = read_env()
    validate_env(ENV)
    TRADE_ENABLED, status = trade_env_ready(ENV)
    poll_seconds = int(ENV.get('POLL_SECONDS') or '15')
    state = load_state()
    try:
        rules = refresh_exchange_info(force=True)
        leverage_count = sum(1 for rule in rules.values() if (rule or {}).get('max_leverage'))
        if leverage_count:
            log(f'已检查并写入合约最大杠杆倍数 | 共{leverage_count}个合约')
        else:
            log('已检查最大杠杆，但未读取到合约数据')
    except Exception as e:
        log(f'检查最大杠杆失败: {e}')
    if TRADE_ENABLED:
        total, available = fetch_collateral()
        log(f'WEEX 跟单启动 | 总权益={total}U | 可用={available}U | 每{poll_seconds}s请求一次信号')
    else:
        log(f'{status} | 每{poll_seconds}s请求一次信号')
    while True:
        try:
            ENV = read_env()
            validate_env(ENV)
            TRADE_ENABLED, _ = trade_env_ready(ENV)
            poll_seconds = int(ENV.get('POLL_SECONDS') or poll_seconds)
            refresh_exchange_info()
            if TRADE_ENABLED:
                manage_active_trade(state)
            signal = fetch_latest_signal()
            maybe_open_from_signal(state, signal)
        except Exception as e:
            log(f'运行错误: {e}')
        time.sleep(poll_seconds)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n用户已停止程序')
    except Exception as e:
        print(f'\n启动失败：{e}', flush=True)
        sys.exit(1)
