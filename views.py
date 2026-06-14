import requests
import json
import time
from django.shortcuts import render
from decouple import config

# اطلاعات پنل ثنایی خودت رو باید اینجا وارد کنی
XUI_URL = config('XUI_URL')
XUI_USERNAME = config('XUI_USERNAME')
XUI_PASSWORD = config('XUI_PASSWORD')

def parse_vless(link):
    try:
        if not link.startswith("vless://"):
            return None
        uuid = link.split('://')[1].split('@')[0]
        return uuid
    except:
        return None

def format_bytes(size):
    return round(size / (1024 ** 3), 2)

def check_config(request):
    if request.method == "GET":
        return render(request, "index.html")

    elif request.method == "POST":
        vless_link = request.POST.get("vless_link", "").strip()
        uuid = parse_vless(vless_link)

        if not uuid:
            return render(request, "index.html", {"error": "لینک وارد شده نامعتبر است. حتما باید لینک vless باشد."})

        session = requests.Session()
        
        try:
            login_url = f"{XUI_URL}/login"
            login_data = {"username": XUI_USERNAME, "password": XUI_PASSWORD}
            login_res = session.post(login_url, data=login_data, timeout=5)
            
            if not login_res.json().get('success'):
                return render(request, "index.html", {"error": "خطا در اتصال به سرور (مشکل لاگین)"})

            stats_url = f"{XUI_URL}/panel/api/inbounds/list"
            stats_res = session.get(stats_url, timeout=5)
            inbounds_data = stats_res.json()

            if not inbounds_data.get('success'):
                 return render(request, "index.html", {"error": "خطا در دریافت اطلاعات از سرور"})

            inbounds = inbounds_data.get('obj', [])
            
            for inbound in inbounds:
                client_stats = inbound.get('clientStats', [])
                settings = json.loads(inbound.get('settings', '{}'))
                clients = settings.get('clients', [])

                for client in clients:
                    if client.get('id') == uuid:
                        email = client.get('email') # نام کاربر
                        expiry_time = client.get('expiryTime', 0) # زمان انقضا
                        
                        # محاسبه روزهای باقی‌مانده
                        if expiry_time == 0:
                            days_remaining = "نامحدود"
                        else:
                            current_time_ms = int(time.time() * 1000)
                            if expiry_time < current_time_ms:
                                days_remaining = "منقضی شده"
                            else:
                                days = int((expiry_time - current_time_ms) / (1000 * 60 * 60 * 24))
                                days_remaining = f"{days} روز"
                        
                        # پیدا کردن حجم مصرفی
                        for stat in client_stats:
                            if stat.get('email') == email:
                                total = stat.get('total', 0)
                                up = stat.get('up', 0)
                                down = stat.get('down', 0)
                                
                                used = up + down
                                
                                return render(request, "index.html", {
                                    "result": {
                                        "username": email,
                                        "total": format_bytes(total) if total > 0 else "نامحدود",
                                        "used": format_bytes(used),
                                        "remaining_time": days_remaining
                                    }
                                })
            
            return render(request, "index.html", {"error": "این کانفیگ در سرور یافت نشد."})

        except Exception as e:
            print(e)
            return render(request, "index.html", {"error": "خطای ارتباط با سرور رخ داد."})