import requests
import time
import datetime
import sys
import os
import re
import configparser
import urllib3
urllib3.disable_warnings()

# ===============================================
#  固定配置
# ===============================================
HOST     = "10.2.5.251"
SUFFIX_MAP = {
    "1": "@cmcc",
    "2": "@dx",
    "3": "@lt",
    "4": "@xyw",
}

RETRY_INTERVAL = 300
KEEP_ALIVE     = 1800

FORBIDDEN_START = datetime.time(23, 30)
FORBIDDEN_END   = datetime.time(8, 0)
# ===============================================


def get_config_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'config.ini')


def load_or_create_config():
    path = get_config_path()
    cfg = configparser.ConfigParser()

    if os.path.exists(path):
        cfg.read(path, encoding='utf-8')
        return cfg['account']['username'], cfg['account']['password'], cfg['account']['suffix']

    print("首次运行，请配置账号信息（将保存在本地 config.ini）")
    print()
    username = input("请输入学号: ").strip()
    password = input("请输入密码: ").strip()
    print("请选择运营商:")
    print("  1. 中国移动")
    print("  2. 中国电信")
    print("  3. 中国联通")
    print("  4. 校园网")
    choice = input("请输入编号 (1-4): ").strip()
    suffix = SUFFIX_MAP.get(choice, "@cmcc")

    cfg['account'] = {'username': username, 'password': password, 'suffix': suffix}
    with open(path, 'w', encoding='utf-8') as f:
        cfg.write(f)
    print(f"已保存配置到 {path}")
    print()
    return username, password, suffix



def get_page_params():
    """从登录页提取用户 IP 和 MAC"""
    NO_PROXY = {'http': '', 'https': ''}
    try:
        r = requests.get(f'http://{HOST}/', timeout=8, verify=False, proxies=NO_PROXY)
        text = r.text
        m_ip  = re.search(r'ss5="([^"]+)"', text)
        m_mac = re.search(r"olmac='([^']+)'", text)
        user_ip  = m_ip.group(1).strip()  if m_ip  else ''
        user_mac = m_mac.group(1).strip() if m_mac else ''
        return user_ip, user_mac
    except Exception:
        return '', ''


def is_forbidden_time():
    now = datetime.datetime.now().time()
    if FORBIDDEN_START <= now or now < FORBIDDEN_END:
        return True
    return False


def wait_until_allowed():
    print("[等待] 当前处于禁止时段 (23:30-08:00)，等待到 08:00 后自动登录...")
    while is_forbidden_time():
        now = datetime.datetime.now()
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now.time() >= FORBIDDEN_START:
            target += datetime.timedelta(days=1)
        wait_sec = int((target - now).total_seconds()) + 1
        wait_min = wait_sec // 60
        print(f"  距 08:00 还有约 {wait_min} 分钟，休眠中...")
        time.sleep(min(wait_sec, 600))


def is_online():
    """直接查询门户认证状态，不走代理"""
    NO_PROXY = {'http': '', 'https': ''}
    try:
        ts = int(time.time() * 1000)
        params = {'c': 'Portal', 'a': 'getOnlineUserInfo', 'callback': f'dr{ts}', '_': str(ts)}
        r = requests.get(f'http://{HOST}:801/eportal/', params=params, timeout=8, verify=False, proxies=NO_PROXY)
        m = re.search(r'"result"\s*:\s*"?(\d+)"?', r.text)
        if m and m.group(1) == '1':
            return True
    except Exception:
        pass
    return False


def do_login(username, password, suffix):
    NO_PROXY = {'http': '', 'https': ''}
    user_ip, user_mac = get_page_params()
    ts = int(time.time() * 1000)

    params = {
        'c':            'Portal',
        'a':            'login',
        'callback':     f'dr{ts}',
        'login_method': '1',
        'user_account': f'{username}{suffix}',
        'user_password': password,
        'wlan_user_ip':  user_ip,
        'wlan_user_mac': user_mac,
        'wlan_ac_ip':    '',
        'wlan_ac_name':  'NAS',
        'jsVersion':     '3.0',
        '_':             str(ts),
    }

    try:
        r = requests.get(
            f'http://{HOST}:801/eportal/',
            params=params, timeout=10, verify=False, proxies=NO_PROXY
        )
        print(f"  [响应] {r.text[:300]}")
        # JSONP 响应，提取 result
        m = re.search(r'"result"\s*:\s*"?(\d+)"?', r.text)
        if m and m.group(1) == '1':
            return True
        m2 = re.search(r'"msg"\s*:\s*"([^"]+)"', r.text)
        if m2:
            print(f"  [消息] {m2.group(1)}")
    except Exception as e:
        print(f"  [错误] {e}")
    return False


def main():
    username, password, suffix = load_or_create_config()
    print('=' * 45)
    print('  校园网自动登录 (Dr.COM)')
    print(f'  账号: {username}{suffix}')
    print('=' * 45)

    while True:
        if is_forbidden_time():
            wait_until_allowed()

        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        if is_online():
            print(f"[{now_str}] 网络正常，{KEEP_ALIVE // 60} 分钟后探活...")
            time.sleep(KEEP_ALIVE)
        else:
            print(f"[{now_str}] 未检测到网络，正在登录...")
            if do_login(username, password, suffix):
                print(f"[{now_str}] 登录成功！{KEEP_ALIVE // 60} 分钟后探活...")
                time.sleep(KEEP_ALIVE)
            else:
                print(f"[{now_str}] 登录失败，{RETRY_INTERVAL // 60} 分钟后重试...")
                time.sleep(RETRY_INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n已手动退出。")
        sys.exit(0)
