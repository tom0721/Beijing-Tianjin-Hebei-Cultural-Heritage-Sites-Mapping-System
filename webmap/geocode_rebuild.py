# -*- coding: utf-8 -*-
"""
批量调用高德地理编码 API,对 heritage.geojson 的 1838 条文保单位重新取精确坐标。
- 输入: webmap/heritage.geojson (WGS84)
- 输出: 覆盖 webmap/heritage.geojson,坐标直接为 GCJ-02(高德坐标系)
- 说明: 高德个人版地理编码约 1 次/秒滑动窗口; 串行 + 短重试, 全程约 35-45 分钟
- 断点续跑: 已标记 coord_src=="geocode" 的条目跳过; fallback 的条目重试
运行: python -X utf8 geocode_rebuild.py
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

KEY = os.environ.get("AMAP_KEY", "")   # 高德 Web 服务 Key, 从环境变量读取, 请勿硬编码入库
if not KEY:
    raise SystemExit("缺少高德 API Key: 请先设置环境变量 AMAP_KEY 后重试")
SRC = r"E:\ARCGIS\xiangmu\webmap\heritage.geojson"
TMP = r"E:\ARCGIS\xiangmu\webmap\heritage.geojson.tmp"
LOG = r"E:\ARCGIS\xiangmu\webmap\geocode_rebuild.log"
API = "https://restapi.amap.com/v3/geocode/geo"
CITY_MAP = {"北京城区": "北京市", "天津城区": "天津市"}
FATAL = {"10001", "10002", "10003", "10009", "10012", "10014", "10016", "10018", "10019", "10020"}
RETRYABLE = {"10021", "30001"}
INTERVAL = 1.05  # 秒/条(高德约 1 次/秒)


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------- WGS84 -> GCJ-02 标准算法(兜底用) ----------
def _tlat(x, y):
    ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
    ret += (160.0*math.sin(y/12.0*math.pi) + 320*math.sin(y*math.pi/30.0)) * 2.0/3.0
    return ret

def _tlng(x, y):
    ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
    ret += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
    return ret

def wgs2gcj(lng, lat):
    a, ee = 6378245.0, 0.00669342162296594323
    dlat = _tlat(lng-105.0, lat-35.0)
    dlng = _tlng(lng-105.0, lat-35.0)
    radlat = lat/180.0*math.pi
    magic = math.sin(radlat)
    magic = 1 - ee*magic*magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat*180.0)/((a*(1-ee))/(magic*sqrtmagic)*math.pi)
    dlng = (dlng*180.0)/(a/sqrtmagic*math.cos(radlat)*math.pi)
    return lng+dlng, lat+dlat


def _req(address, city):
    params = {"address": address, "key": KEY, "output": "JSON"}
    if city:
        params["city"] = city
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(name, city):
    """返回 (status, glng, glat, addr, note)  status: ok/fallback/fatal"""
    variants = [name]
    if city and city not in name:
        variants.append(city + name)
    for vi, addr in enumerate(variants):
        for attempt in range(3):
            try:
                data = _req(addr, city)
            except Exception:
                time.sleep(1.05 + attempt)   # 网络异常: 短暂等待后重试
                continue
            st = data.get("status")
            if st == "1":
                gs = data.get("geocodes") or []
                if gs:
                    loc = gs[0].get("location", "").split(",")
                    if len(loc) == 2:
                        return "ok", float(loc[0]), float(loc[1]), gs[0].get("formatted_address", ""), ""
                return "fallback", None, None, "", "no_geocode:" + addr
            info = data.get("infocode", "")
            if info in FATAL:
                return "fatal", None, None, "", "%s:%s" % (info, data.get("info", ""))
            if info in RETRYABLE:
                time.sleep(1.05 + attempt)   # 限流/服务端临时错误: 1s 后即恢复
                continue
            return "fallback", None, None, "", "api_error:%s:%s" % (info, data.get("info", ""))
    return "fallback", None, None, "", "tries_exhausted"


def main():
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    feats = data["features"]
    total = len(feats)
    log("共 %d 条, 开始批量地理编码(约 35-45 分钟)" % total)

    done = {}
    if os.path.exists(TMP):
        with open(TMP, encoding="utf-8") as f:
            tmp = json.load(f)
        if len(tmp["features"]) == total:
            for ft in tmp["features"]:
                p = ft["properties"]
                if p.get("coord_src") == "geocode":
                    done[p["name"] + p.get("city", "")] = ft
            log("从临时快照续跑, 已精确定位 %d 条, 本次跳过" % len(done))

    ok = fall = 0
    last_save = time.time()
    for i, ft in enumerate(feats):
        p = ft["properties"]
        key = p["name"] + p.get("city", "")
        if key in done:
            feats[i] = done[key]
            ok += 1
            continue
        city = CITY_MAP.get(p.get("city", ""), p.get("city", ""))
        status, glng, glat, addr, note = geocode(p["name"], city)
        if status == "fatal":
            with open(TMP, "w", encoding="utf-8") as f:
                json.dump({"features": feats}, f, ensure_ascii=False)
            log("致命错误, 停止: %s (已完成 %d 条)" % (note, i))
            return
        p["wgs_lon"], p["wgs_lat"] = p["lon"], p["lat"]
        if status == "ok":
            p["gcj_lon"], p["gcj_lat"] = glng, glat
            p["geo_addr"] = addr
            p["coord_src"] = "geocode"
            ft["geometry"]["coordinates"] = [glng, glat]
            ok += 1
        else:
            glng, glat = wgs2gcj(p["lon"], p["lat"])
            p["gcj_lon"], p["gcj_lat"] = glng, glat
            p["geo_addr"] = ""
            p["coord_src"] = "fallback_local"
            p["gcj_note"] = note
            ft["geometry"]["coordinates"] = [glng, glat]
            fall += 1
        if (i + 1) % 100 == 0:
            log("[%d/%d] 精确定位 %d 回退 %d" % (i+1, total, ok, fall))
        if time.time() - last_save > 180:
            with open(TMP, "w", encoding="utf-8") as f:
                json.dump({"features": feats}, f, ensure_ascii=False)
            last_save = time.time()
        time.sleep(INTERVAL)

    with open(SRC, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    if os.path.exists(TMP):
        os.remove(TMP)
    log("完成: 共 %d 条, API精确定位 %d, 本地回退 %d" % (total, ok, fall))


if __name__ == "__main__":
    main()
