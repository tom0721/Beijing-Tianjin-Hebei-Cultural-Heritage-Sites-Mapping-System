# 京津冀文物保护单位地图 · Web GIS Demo

基于论文《京津冀地区文化遗产空间分布影响因素分析》的 GIS 数据,搭建的在线地图项目(MVP/测试版)。

## 功能

- **默认政区图**:高德政区底图(中文注记),叠加京津冀 13 地市边界
- **卫星图开关**:右上角一键叠加卫星影像
- **3D 高程开关**:启用全球地形(terrain),打开时**自动叠加卫星图**,可倾斜旋转看地形起伏
- **文保单位点位**:1838 处省级及以上文保单位(国家级 451 + 省级 1387),按级别分色
- **点击弹窗**:名称、级别、时代、所属市、经纬度、高程、图片位、百度搜索外链
- **名称搜索**:顶部搜索框,模糊匹配(包含匹配),实时建议列表,点击后自动飞行定位 + 橙色高亮 + 信息弹窗

## 目录结构

```
项目根/
├── index.html            # 成品页面(内联数据, 双击即开 / GitHub Pages 站点入口)
├── libs/                 # MapLibre GL JS 4.7.1(本地化, 不依赖 CDN)
├── webmap/
│   ├── index.template.html   # 页面模板({{HERITAGE_DATA}}/{{BOUNDARY_DATA}} 占位)
│   ├── build.py              # 数据管线: dbf/geoJson -> geojson -> 根目录 index.html
│   ├── geocode_rebuild.py    # 高德 API 批量坐标纠偏(GCJ-02)
│   ├── heritage.geojson      # 1838 个文保单位点位(GCJ-02, 数据资产)
│   ├── boundary.geojson      # 京津冀 13 地市边界(GCJ-02)
│   └── assets/               # 预留: 文物图片等静态资源
└── README.md
```

## 运行方式

1. **直接双击** `index.html`(需联网加载底图瓦片)
2. 或本地起服务:`python -m http.server 8000` 后访问 http://localhost:8000/
3. **在线版(GitHub Pages)**:https://tom0721.github.io/Beijing-Tianjin-Hebei-Cultural-Heritage-Sites-Mapping-System/
   - 页面根目录托管, 更新时重新运行 `python webmap/build.py` 并推送即可

## 数据与构建

- **坐标精修(高德 API)**:`python webmap/geocode_rebuild.py`
  - 对 1838 条按「名称+城市」批量调高德地理编码 API,重新取精确坐标
  - 输出坐标直接为 **GCJ-02**(高德坐标系),页面不再做任何坐标转换
  - 高德个人版限速约 1 QPS,全程约 33 分钟,支持断点续跑(已定位的跳过)
  - 匹配失败条目自动回退本地 WGS84→GCJ-02 转换,并在弹窗标注"本地转换(待精修)"
- 坐标系:全链路 **GCJ-02**(点位/边界/底图统一);原始 WGS84 坐标保留在 properties.wgs_lon/wgs_lat 供审计

## 待准备 / 可扩展

- [ ] 文物图片:在 `heritage.geojson` 的 `img` 字段填图片 URL(或放 `assets/`),弹窗自动显示
- [ ] 数据更新:文物局名录更新后重跑 `build.py`
- [ ] 部署上线:GitHub Pages / Vercel / 云服务器(静态托管即可)
- [ ] 搜索增强:拼音首字母匹配、分类筛选
- [ ] 市级及以下文保单位数据接入
- [ ] 论文分析功能在线化:核密度、缓冲区、高程统计等

## 说明

- 底图瓦片来自高德地图(公开瓦片服务,仅演示用),3D 地形来自 AWS Terrarium(免费)
- 点位数据源自毕业论文研究整理,仅作学习演示
