import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / '跟单.env'
RUN_SCRIPT = ROOT / 'WEEX交易所.py'

FIELDS = [
    ('SUB_CODE', '注册码', False),
    ('WEEX_API_KEY', 'WEEX API Key', False),
    ('WEEX_API_SECRET', 'WEEX API Secret', True),
    ('WEEX_API_PASSPHRASE', 'WEEX API Passphrase', True),
    ('WEEX_ORDER_USDT', '每单本金 USDT', False),
]


def read_env_lines():
    if not ENV_PATH.exists():
        return []
    return ENV_PATH.read_text(encoding='utf-8').splitlines()


def read_env_values():
    values = {}
    for line in read_env_lines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def write_env_values(updates):
    lines = read_env_lines()
    seen = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in updates:
                new_lines.append(f'{key}={updates[key]}')
                seen.add(key)
                continue
        new_lines.append(line)

    missing = [(key, value) for key, value in updates.items() if key not in seen]
    if missing:
        insert_at = 0
        for idx, line in enumerate(new_lines):
            if line.strip().startswith('# 合约最大杠杆倍数'):
                insert_at = max(0, idx - 1)
                break
        block = [f'{key}={value}' for key, value in missing]
        new_lines[insert_at:insert_at] = block + ['']

    ENV_PATH.write_text('\n'.join(new_lines).rstrip() + '\n', encoding='utf-8')


def run_trader():
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    subprocess.call([sys.executable, '-u', str(RUN_SCRIPT)], cwd=str(ROOT))


def cli_setup():
    values = read_env_values()
    print('WEEX 交易所安装配置')
    print('请按提示填写。WEEX API 不填也可以，只会监听信号，不会自动下单。')
    updates = {}
    for key, label, secret in FIELDS:
        current = values.get(key, '')
        prompt = f'{label}'
        if current:
            prompt += f' [{current if not secret else "已填写"}]'
        prompt += ': '
        value = input(prompt).strip()
        updates[key] = value if value else current
    write_env_values(updates)
    print('配置已保存。')
    answer = input('是否现在启动跟单？输入 y 启动，直接回车退出: ').strip().lower()
    if answer == 'y':
        run_trader()


def gui_setup():
    import tkinter as tk
    from tkinter import messagebox

    values = read_env_values()
    root = tk.Tk()
    root.title('WEEX 交易所安装配置')
    root.geometry('520x330')
    root.resizable(False, False)

    title = tk.Label(root, text='WEEX 交易所跟单配置', font=('Arial', 18, 'bold'))
    title.pack(pady=(18, 6))
    hint = tk.Label(root, text='填写注册码、WEEX API 和每单本金。API 不填时只监听信号，不会自动下单。')
    hint.pack(pady=(0, 12))

    frame = tk.Frame(root)
    frame.pack(fill='x', padx=28)

    entries = {}
    for row, (key, label, secret) in enumerate(FIELDS):
        tk.Label(frame, text=label, anchor='w', width=18).grid(row=row, column=0, sticky='w', pady=6)
        entry = tk.Entry(frame, width=42, show='*' if secret else '')
        entry.insert(0, values.get(key, ''))
        entry.grid(row=row, column=1, sticky='ew', pady=6)
        entries[key] = entry

    def collect_updates():
        updates = {key: entry.get().strip() for key, entry in entries.items()}
        if not updates.get('SUB_CODE'):
            messagebox.showerror('缺少注册码', '请填写注册码 SUB_CODE。')
            return None
        if not updates.get('WEEX_ORDER_USDT'):
            updates['WEEX_ORDER_USDT'] = '20'
        return updates

    def save_only():
        updates = collect_updates()
        if updates is None:
            return
        write_env_values(updates)
        messagebox.showinfo('保存成功', '配置已保存。')

    def save_and_run():
        updates = collect_updates()
        if updates is None:
            return
        write_env_values(updates)
        root.destroy()
        run_trader()

    buttons = tk.Frame(root)
    buttons.pack(pady=22)
    tk.Button(buttons, text='保存配置', width=14, command=save_only).pack(side='left', padx=8)
    tk.Button(buttons, text='保存并启动跟单', width=18, command=save_and_run).pack(side='left', padx=8)

    root.mainloop()


if __name__ == '__main__':
    try:
        gui_setup()
    except Exception as exc:
        print(f'图形配置页面启动失败，改用文字配置。原因: {exc}')
        cli_setup()
