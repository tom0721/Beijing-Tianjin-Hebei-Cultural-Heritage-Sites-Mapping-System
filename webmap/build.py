# -*- coding: utf-8 -*-
"""京津冀文保地图 MVP · 数据管线与页面构建

用法:  python build.py
输入:  gis/新建文件夹/终版/京津冀文物保护单位包含高程.dbf  (2340 条)
       gis/新建文件夹/北京市.geoJson / 天津市.geoJson / 河北省.geoJson
输出:  webmap/heritage.geojson   1838 个去重点位(国家级优先)
       webmap/boundary.geojson   京津冀 13 地市边界
       webmap/index.html         内联数据的演示页面(双击即开)
"""
import os
import json
import math
from collections import Counter

from dbfread import DBF
from shapely.geometry import shape, Point

BASE = os.path.dirname(os.path.abspath(__file__))          # webmap/
PROJECT = os.path.dirname(BASE)                              # 项目根
GIS = os.path.join(PROJECT, "gis", "新建文件夹")

LEVEL_MAP = {0: "国家级", 1: "省级"}
PROVS = ["北京市", "天津市", "河北省"]


# ---------- WGS84 -> GCJ-02 标准算法(边界/兜底用) ----------
def _tlat(x, y):
    r = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    r += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    r += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
    r += (160.0*math.sin(y/12.0*math.pi) + 320*math.sin(y*math.pi/30.0)) * 2.0/3.0
    return r

def _tlng(x, y):
    r = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    r += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    r += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
    r += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
    return r

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

def toGCJ(geom):
    if geom["type"] == "Point":
        geom["coordinates"] = wgs2gcj(geom["coordinates"][0], geom["coordinates"][1])
    elif geom["type"] == "Polygon":
        geom["coordinates"] = [[wgs2gcj(c[0], c[1]) for c in ring] for ring in geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        geom["coordinates"] = [[[wgs2gcj(c[0], c[1]) for c in ring] for ring in poly]
                               for poly in geom["coordinates"]]
    return geom


def load_points():
    """读 dbf, 按(名称, 坐标)去重, 国家级优先"""
    p = os.path.join(GIS, "终版", "京津冀文物保护单位包含高程.dbf")
    rows = list(DBF(p, encoding="utf-8"))
    best = {}
    for r in rows:
        key = (str(r["名称"]).strip(), round(float(r["lon"]), 6), round(float(r["lat"]), 6))
        lv = int(r["级别"])
        if key not in best or lv < int(best[key]["级别"]):
            best[key] = r
    return best


def load_cities():
    """读三市 geoJson, 返回 [{name, geom}]"""
    cities = []
    for prov in PROVS:
        gp = os.path.join(GIS, prov + ".geoJson")
        with open(gp, "r", encoding="utf-8-sig") as f:
            gj = json.load(f)
        for ft in gj["features"]:
            cities.append({"name": ft["properties"]["name"],
                           "geom": shape(ft["geometry"])})
    return cities


def to_features(points, cities):
    feats = []
    for key, r in points.items():
        lon, lat = float(r["lon"]), float(r["lat"])
        pt = Point(lon, lat)
        owner = ""
        for c in cities:
            if c["geom"].contains(pt) or c["geom"].boundary.distance(pt) < 1e-6:
                owner = c["name"]
                break
        elev = r.get("RASTERVALU")
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "name": str(r["名称"]).strip(),
                "level": LEVEL_MAP.get(int(r["级别"]), "省级"),
                "era": str(r["时代"]).strip(),
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "elev": int(round(float(elev))) if elev is not None else None,
                "city": owner,
                "img": "",           # 预留: 图片 URL, 后续批量补充
            }
        })
    return feats


def boundary_features():
    """三市边界 -> geojson, 坐标统一转为 GCJ-02(与底图/点位一致)"""
    feats = []
    for prov in PROVS:
        gp = os.path.join(GIS, prov + ".geoJson")
        with open(gp, "r", encoding="utf-8-sig") as f:
            gj = json.load(f)
        for ft in gj["features"]:
            ft["properties"] = {"name": ft["properties"]["name"]}
            toGCJ(ft["geometry"])
            feats.append(ft)
    return feats


def merge_geocoded(feats):
    """若 heritage.geojson 已含高德纠偏结果(coord_src), 合并进新构建的数据,
    避免重跑 build.py 覆盖精确坐标。新增点位无纠偏结果, 保持 WGS84 待下次纠偏。"""
    p = os.path.join(BASE, "heritage.geojson")
    if not os.path.exists(p):
        return feats
    with open(p, "r", encoding="utf-8") as f:
        old = json.load(f)
    oldmap = {}
    for ft in old["features"]:
        pp = ft["properties"]
        if pp.get("coord_src"):
            oldmap[(pp["name"], pp.get("city", ""))] = ft
    n = 0
    for ft in feats:
        pp = ft["properties"]
        key = (pp["name"], pp.get("city", ""))
        if key in oldmap:
            o = oldmap[key]["properties"]
            for k in ("wgs_lon", "wgs_lat", "gcj_lon", "gcj_lat", "geo_addr", "coord_src", "gcj_note"):
                if k in o:
                    pp[k] = o[k]
            ft["geometry"]["coordinates"] = [o["gcj_lon"], o["gcj_lat"]]
            n += 1
    if n:
        print("合并已纠偏坐标:", n, "条")
    return feats


def inline_json(obj):
    """JSON 内联进 <script>, 防止 </ 提前闭合标签"""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def main():
    os.makedirs(BASE, exist_ok=True)

    points = load_points()
    cities = load_cities()
    feats = to_features(points, cities)
    feats = merge_geocoded(feats)   # 保留高德纠偏结果
    heritage = {"type": "FeatureCollection", "features": feats}

    boundary = {"type": "FeatureCollection", "features": boundary_features()}

    with open(os.path.join(BASE, "heritage.geojson"), "w", encoding="utf-8") as f:
        json.dump(heritage, f, ensure_ascii=False)
    with open(os.path.join(BASE, "boundary.geojson"), "w", encoding="utf-8") as f:
        json.dump(boundary, f, ensure_ascii=False)

    # 统计
    lv_cnt = Counter(f["properties"]["level"] for f in feats)
    city_cnt = Counter(f["properties"]["city"] for f in feats if f["properties"]["city"])
    print("点位:", len(feats), dict(lv_cnt))
    print("未归属市:", sum(1 for f in feats if not f["properties"]["city"]))
    print("边界:", len(boundary["features"]), "个地市")
    print("地市分布:", dict(city_cnt.most_common()))

    # 构建 index.html(内联数据), 输出到项目根目录(供 GitHub Pages 直接托管)
    tpl_path = os.path.join(BASE, "index.template.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    html = (tpl
            .replace("{{HERITAGE_DATA}}", inline_json(heritage))
            .replace("{{BOUNDARY_DATA}}", inline_json(boundary)))
    out_path = os.path.join(PROJECT, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("index.html 已生成 (%.1f KB)" % (os.path.getsize(out_path) / 1024))


if __name__ == "__main__":
    main()
