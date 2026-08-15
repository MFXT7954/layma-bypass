import os, re, json, time, uuid, random, base64, threading
from flask import Flask, request, Response, render_template, jsonify
import requests as req

app = Flask(__name__)

# ── API KEYS ──────────────────────────────────────────────────────────────────
NONECAP_KEYS = [
    "nc_live_6TM0aKdCfFIuRfl9Vj0zyNw2K7n3wV7k",
    "nc_live_lXkRpY_DO17Rdm7nx1_s5-AdK1OMGphq",
    "nc_live_QOj9kQ5Uh8TN9gCL21Nq2aSelbw8rGcd",
    "nc_live_CFw9sYuqyLZzUjqi8fpBR649U4A5M3xC",
    "nc_live_5gvwxofUXnQQlWLadUzrnwiqDqRXwFLF",
    "nc_live_UCZcA_8Xkh0sJBrCpqhjG6qnbDp0oN7K",
    "nc_live_pXk_YC4Nmtd4u6Y87T15mjV09DNewU27",
    "nc_live_5BkQySnVL6ZsMISEELGozOSCPYYovWc0",
    "nc_live_5m60EvhJLAgJcy4bukhJTpvKowFK9G66",
]
WITAI_TOKEN   = "FTOEYXPM22RSBYY52Z7X66GSZLZIAUD4"
CAPSOLVER_KEY = "CAP-58D8F04E6382EC2CC48EB334D3C5E60B1FD872507F9959D3FB45128B360F3555"
LAYMA_RECAPTCHA_SITEKEY = "6Lfooa4qAAAAAHII9gQNvDNfIf2-vUwlSiJNUuM6"

DEAD_DOMAINS = {"ndomark.co", "s1.what-on.com", "belitungtour.co"}

FINGERPRINT = {
    "version": "v1",
    "uuid": "7f3d9a2b-e841-4c5f-a318-9d2e4f7b1c6a",
    "language": "vi-VN", "platform": "Win32",
    "browser": "Chrome", "browserVersion": "120.0",
    "browserMajorVersion": "120",
    "screen": "1366 x 768", "colorDepth": 24, "pixelRatio": 1,
    "battery": {"level": 85, "charging": True, "chargingTime": 0},
    "orientation": {"supported": True, "granted": True, "available": True},
    "createdAt": "2026-08-12T09:00:00.000Z",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "vi-VN,vi;q=0.9"}

# ── NONECAP SOLVER ────────────────────────────────────────────────────────────
_key_idx = 0
_key_lock = threading.Lock()

def _next_key():
    global _key_idx
    with _key_lock:
        k = NONECAP_KEYS[_key_idx % len(NONECAP_KEYS)]
        _key_idx += 1
        return k

def solve_hcaptcha(sitekey: str, page_url: str, log) -> str | None:
    for attempt in range(len(NONECAP_KEYS) * 2):
        key = _next_key()
        log(f"[hCaptcha] NoneCap key #{attempt+1}: {key[:24]}...")
        try:
            r = req.post("https://api.noncaptcha.io/createTask", json={
                "clientKey": key,
                "task": {"type": "HCaptchaTaskProxyless", "websiteURL": page_url, "websiteKey": sitekey}
            }, timeout=30)
            data = r.json()
            if data.get("errorCode") in ("ERROR_KEY_DOES_NOT_EXIST", "ERROR_NO_SLOT_AVAILABLE", "ERROR_ZERO_BALANCE"):
                log(f"[hCaptcha] Key exhausted, rotating...")
                continue
            task_id = data.get("taskId")
            if not task_id:
                log(f"[hCaptcha] No taskId: {data}")
                continue
            for _ in range(60):
                time.sleep(5)
                res = req.post("https://api.noncaptcha.io/getTaskResult", json={
                    "clientKey": key, "taskId": task_id
                }, timeout=15).json()
                if res.get("status") == "ready":
                    token = res["solution"]["gRecaptchaResponse"]
                    log(f"[hCaptcha] Solved ✓")
                    return token
                if res.get("errorCode"):
                    log(f"[hCaptcha] Error: {res['errorCode']}")
                    break
        except Exception as e:
            log(f"[hCaptcha] Exception: {e}")
    return None

# ── WIT.AI RECAPTCHA AUDIO SOLVER ─────────────────────────────────────────────
def solve_recaptcha_witai(page_url: str, log) -> str | None:
    try:
        log("[reCaptcha] Fetching anchor token...")
        anchor_url = (
            f"https://www.google.com/recaptcha/api2/anchor"
            f"?ar=1&k={LAYMA_RECAPTCHA_SITEKEY}&co=aHR0cHM6Ly9sYXltYS5uZXQ6NDQz"
            f"&hl=vi&v=rAnd0m&size=invisible&cb=xyz"
        )
        r = req.get(anchor_url, headers=HEADERS, timeout=15)
        token_match = re.search(r'"recaptcha-token" value="([^"]+)"', r.text)
        if not token_match:
            log("[reCaptcha] anchor token not found")
            return None
        anchor_token = token_match.group(1)
        log(f"[reCaptcha] Anchor token: {anchor_token[:30]}...")

        log("[reCaptcha] Requesting audio challenge...")
        reload_r = req.post(
            f"https://www.google.com/recaptcha/api2/reload?k={LAYMA_RECAPTCHA_SITEKEY}",
            data={"v": "rAnd0m", "reason": "q", "c": anchor_token,
                  "k": LAYMA_RECAPTCHA_SITEKEY, "co": "aHR0cHM6Ly9sYXltYS5uZXQ6NDQz",
                  "hl": "vi", "size": "invisible", "chr": "%5B89%2C64%2C27%5D",
                  "vh": "13612688948", "bg": "!GgA", "type": "audio"},
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15
        )
        audio_match = re.search(r'"audio_src":"([^"]+)"', reload_r.text)
        if not audio_match:
            log("[reCaptcha] No audio src found")
            return None
        audio_url = audio_match.group(1).replace("\\u003d", "=").replace("\\u0026", "&")
        log(f"[reCaptcha] Audio URL: {audio_url[:60]}...")

        audio_bytes = req.get(audio_url, headers=HEADERS, timeout=20).content
        log(f"[reCaptcha] Downloaded audio {len(audio_bytes)} bytes")

        log("[reCaptcha] Sending to Wit.ai...")
        wit_r = req.post(
            "https://api.wit.ai/speech?v=20220622",
            headers={
                "Authorization": f"Bearer {WITAI_TOKEN}",
                "Content-Type": "audio/mpeg3",
            },
            data=audio_bytes,
            timeout=30
        )
        transcript = wit_r.json().get("text", "").strip()
        if not transcript:
            log("[reCaptcha] Wit.ai returned empty transcript")
            return None
        log(f"[reCaptcha] Transcript: '{transcript}'")

        log("[reCaptcha] Submitting answer...")
        verify_r = req.post(
            f"https://www.google.com/recaptcha/api2/userverify?k={LAYMA_RECAPTCHA_SITEKEY}",
            data={"v": "rAnd0m", "c": anchor_token, "response": transcript,
                  "k": LAYMA_RECAPTCHA_SITEKEY},
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15
        )
        uv_match = re.search(r'"uvresp","([^"]+)"', verify_r.text)
        if not uv_match:
            log("[reCaptcha] uvresp not found")
            return None
        token = uv_match.group(1)
        log(f"[reCaptcha] Token acquired ✓")
        return token
    except Exception as e:
        log(f"[reCaptcha] Exception: {e}")
        return None

# ── LAYMA PARSER ──────────────────────────────────────────────────────────────
def parse_layma(url: str, log):
    log(f"[Layma] Fetching: {url}")
    r = req.get(url, headers=HEADERS, timeout=20)
    html = r.text

    token    = re.search(r'keytoken["\s:=]+(["\']?)([A-Za-z0-9_\-]+)\1', html)
    camp_id  = re.search(r'campainId["\s:=]+(["\']?)([A-Za-z0-9_\-]+)\1', html)
    mission  = re.search(r'mission["\s:=]+(["\']?)([A-Za-z0-9_\-]+)\1', html)

    token   = token.group(2)   if token   else None
    camp_id = camp_id.group(2) if camp_id else None
    mission = mission.group(2) if mission else None

    log(f"[Layma] token={token} campainId={camp_id} mission={mission}")

    task_url  = re.search(r'href=["\']?(https?://[^\s"\'<>]+)["\']?[^>]*>\s*(?:Truy cập|Visit|Go)', html, re.I)
    task_kw   = re.search(r'data-clipboard-text=["\']([^"\']+)["\']', html)
    tk1       = re.search(r'TK1["\s:=]+(["\']?)([^"\'<>\s]+)\1', html)
    tk3       = re.search(r'TK3["\s:=]+(["\']?)([^"\'<>\s]+)\1', html)

    return {
        "token": token, "camp_id": camp_id, "mission": mission,
        "task_url": task_url.group(1) if task_url else None,
        "task_kw":  task_kw.group(1)  if task_kw  else (tk1.group(2) if tk1 else (tk3.group(2) if tk3 else None)),
        "html": html,
    }

def change_mission(token: str, camp_id: str, log):
    log("[Layma] Changing mission...")
    try:
        req.post("https://api.layma.net/api/admin/mission/changeMission",
                 json={"keytoken": token, "campainId": camp_id},
                 headers=HEADERS, timeout=15)
    except Exception as e:
        log(f"[Layma] changeMission error: {e}")

# ── TASK SITE SOLVER ──────────────────────────────────────────────────────────
def solve_task_site(task_url: str, layma_token: str, camp_id: str, log) -> str | None:
    from urllib.parse import urlparse
    domain = urlparse(task_url).netloc
    if domain in DEAD_DOMAINS:
        log(f"[Task] Dead domain {domain}, skip")
        return None

    log(f"[Task] Visiting: {task_url}")
    r = req.get(task_url, headers=HEADERS, timeout=20)
    html = r.text

    sitekey_match = re.search(r'hCaptchaSiteKey["\s:=]+(["\']?)([A-Za-z0-9_\-]+)\1', html)
    if not sitekey_match:
        log("[Task] hCaptchaSiteKey not found in page")
        return None
    sitekey = sitekey_match.group(2)
    log(f"[Task] hCaptchaSiteKey: {sitekey}")

    log("[Task] GET campain (initial)...")
    camp_r = req.get(
        f"https://api.layma.net/api/admin/campain"
        f"?keytoken={layma_token}&flatform=facebook&sessionToken=&waitMode=1&requiredPageVisits=1",
        headers=HEADERS, timeout=15
    ).json()
    session_token = camp_r.get("sessionToken") or camp_r.get("data", {}).get("sessionToken", "")
    traffic_id    = camp_r.get("trafficId")    or camp_r.get("data", {}).get("trafficId", "")
    wait_seconds  = int(camp_r.get("remainingWaitSeconds") or camp_r.get("data", {}).get("remainingWaitSeconds") or 15)
    log(f"[Task] session={session_token} trafficId={traffic_id} wait={wait_seconds}s")

    log(f"[Task] Waiting {wait_seconds}s (ping every 10s)...")
    elapsed = 0
    while elapsed < wait_seconds:
        chunk = min(10, wait_seconds - elapsed)
        time.sleep(chunk)
        elapsed += chunk
        req.get(
            f"https://api.layma.net/api/admin/campain"
            f"?keytoken={layma_token}&flatform=facebook&sessionToken={session_token}",
            headers=HEADERS, timeout=10
        )
        log(f"[Task] Ping {elapsed}/{wait_seconds}s")

    hcap_token = solve_hcaptcha(sitekey, task_url, log)
    if not hcap_token:
        log("[Task] hCaptcha solve failed")
        return None

    log("[Task] POST getcode...")
    fp = {**FINGERPRINT, "uuid": str(uuid.uuid4())}
    payload = {
        "trafficId": traffic_id,
        "trafficSessionToken": session_token,
        "referrer": task_url,
        "solution": hcap_token,
        "hCaptchaToken": hcap_token,
        "hCaptchaTokenDuPhong": "Krprba8mMnrRnL0fCU24uJDqRtZ07ohQ",
        "userAgent": UA,
        "screen": "1366 x 768",
        "browser": "Chrome", "browserVersion": "120.0", "browserMajorVersion": "120",
        "cookies": "", "mobile": False, "os": "Windows", "osVersion": "10",
        "platform": "Win32", "language": "vi-VN",
        "uuid": fp["uuid"], "fingerprintData": json.dumps(fp),
    }
    code_r = req.post(
        "https://api.layma.net/api/admin/codemanager/getcode",
        json=payload, headers=HEADERS, timeout=30
    ).json()
    code = code_r.get("code") or code_r.get("data", {}).get("code")
    log(f"[Task] Code: {code}")
    return code

# ── MAIN BYPASS ───────────────────────────────────────────────────────────────
def bypass_layma(layma_url: str, log):
    MAX_RETRIES = 5
    parsed = None

    for attempt in range(MAX_RETRIES):
        parsed = parse_layma(layma_url, log)
        token   = parsed["token"]
        camp_id = parsed["camp_id"]

        task_url = parsed.get("task_url")
        task_kw  = parsed.get("task_kw")

        if not task_url and not task_kw:
            log(f"[Bypass] No task found (attempt {attempt+1}), changing mission...")
            change_mission(token, camp_id, log)
            time.sleep(2)
            continue

        if task_url:
            from urllib.parse import urlparse
            domain = urlparse(task_url).netloc
            if "facebook.com" in domain:
                log("[Bypass] FB task detected, changing mission...")
                change_mission(token, camp_id, log)
                time.sleep(2)
                continue
            code = solve_task_site(task_url, token, camp_id, log)
        else:
            log(f"[Bypass] Keyword task: {task_kw} — searching task site...")
            code = None

        if not code:
            log("[Bypass] No code, changing mission...")
            change_mission(token, camp_id, log)
            time.sleep(2)
            continue

        log(f"[Bypass] Submitting code to Layma...")
        time.sleep(3)
        check_r = req.post(
            "https://api.layma.net/api/admin/codemanager/checkcode",
            json={"Code": code, "Token": token, "CampainId": camp_id},
            headers=HEADERS, timeout=20
        ).json()
        log(f"[Bypass] checkcode response: {json.dumps(check_r)[:200]}")

        orig_url = (check_r.get("url") or check_r.get("originalUrl")
                    or check_r.get("data", {}).get("url") or check_r.get("data", {}).get("originalUrl"))

        if not orig_url:
            redirect_token = (check_r.get("redirectToken") or check_r.get("data", {}).get("redirectToken"))
            if not redirect_token:
                log("[Bypass] No redirect token, retrying...")
                continue

            log("[Bypass] Solving Layma reCaptcha via Wit.ai audio...")
            rcap_token = solve_recaptcha_witai(layma_url, log)
            if not rcap_token:
                log("[Bypass] reCaptcha failed, retrying...")
                continue

            final_r = req.post(
                "https://api.layma.net/api/admin/codemanager/checkcode",
                json={"Code": code, "Token": token, "CampainId": camp_id,
                      "reCaptchaToken": rcap_token, "redirectToken": redirect_token},
                headers=HEADERS, timeout=20
            ).json()
            orig_url = (final_r.get("url") or final_r.get("originalUrl")
                        or final_r.get("data", {}).get("url") or final_r.get("data", {}).get("originalUrl"))

        if orig_url:
            log(f"[Bypass] ✓ Original URL: {orig_url}")
            return orig_url

        log(f"[Bypass] Attempt {attempt+1} failed, retrying...")

    log("[Bypass] All attempts exhausted.")
    return None

# ── FLASK ROUTES ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/bypass")
def bypass_stream():
    layma_url = request.args.get("url", "").strip()
    if not layma_url:
        return Response("data: [ERROR] No URL provided\n\n", mimetype="text/event-stream")

    def generate():
        logs = []
        result = {"url": None}

        def log(msg):
            logs.append(msg)

        try:
            orig = bypass_layma(layma_url, log)
            result["url"] = orig
        except Exception as e:
            log(f"[FATAL] {e}")

        for msg in logs:
            yield f"data: {msg}\n\n"
            time.sleep(0.05)

        if result["url"]:
            yield f"data: RESULT:{result['url']}\n\n"
        else:
            yield "data: RESULT:ERROR\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
