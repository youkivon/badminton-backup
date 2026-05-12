# 羽毛球视频分析小程序 — 项目规范

## 项目概述

帮助业余羽毛球球员通过视频复盘提升技术的智能分析工具。核心价值：让球员"看清自己的问题，感受到进步"。

- **分析对象**：双打比赛视频，固定观众机位，半场取景，1-7分钟/段
- **分析方式**：VLM 逐帧动作识别 + 技术诊断 + PDF 报告
- **核心逻辑**：每次分析 → 球员档案积累 → 进步对比

---

## 目录结构

```
~/Desktop/小程序/
├── claude.md                          # 本文件（项目规范）
├── 羽毛球视频分析小程序_规划.md         # 产品规划文档
├── badminton_insight_knowledge.toml   # 羽毛球知识库（77篇文章）
├── badminton_insight_articles.json    # 文章原始数据
│
├── src/                               # 核心代码
│   ├── run_analysis.py                # 统一入口（帧提取→VLM分析→存档→报告）
│   ├── vlm_analyzer.py                # VLM 动作分析（硅基流动 Qwen3-VL-32B）
│   ├── report_generator.py            # PDF 报告生成（fpdf2）
│   └── player_db.py                   # 球员档案管理（历史/成就/进步计算）
│
├── players/                           # 球员档案（每人一个文件夹）
│   └── [球员名]/
│       ├── profile.json               # 球员基本信息
│       ├── history/                   # 历次分析记录
│       │   └── YYYY-MM-DD.json
│       └── frame_archive/             # 历次帧图存档
│           └── YYYY-MM-DD/
│
├── reports/                           # 生成的 PDF 报告
│   └── badminton_report_YYYY-MM-DD_HHMMSS.pdf
│
└── data/                               # 临时数据（/tmp/bad_shots/ 的镜像备份）
```

---

## 核心流程

```
视频     → 帧提取（4fps + OpenCV羽毛球检测，有球帧全部送VLM上限150帧）
     → VLM 逐帧分析（并发3路 + 重试）
     → 动作聚合（shots）
     → 保存球员档案（history/ + frame_archive/）
     → 生成 PDF 报告
     → 推送微信（可选）
```

### 运行命令

```bash
# 基本用法
python ~/Desktop/小程序/src/run_analysis.py ~/Desktop/视频.mp4 --player 张三

# 跳过VLM分析（用已有缓存）
python ~/Desktop/小程序/src/run_analysis.py ~/Desktop/视频.mp4 --player 张三 --skip_analysis

# 仅保存记录，不生成PDF
python ~/Desktop/小程序/src/run_analysis.py ~/Desktop/视频.mp4 --player 张三 --session_only

# 指定帧目录（默认 /tmp/bad_shots/target_frames）
python ~/Desktop/小程序/src/run_analysis.py ~/Desktop/视频.mp4 --frames_dir /自定义路径
```

---

## 技术架构

### VLM 分析（vlm_analyzer.py）

- **模型**：硅基流动 Qwen3-VL-32B-Instruct（`Qwen/Qwen3-VL-32B-Instruct`）
- **API**：`https://api.siliconflow.cn/v1/chat/completions`
- **并发**：ThreadPoolExecutor(max_workers=3)，避免触发限流
- **重试**：MAX_RETRIES=3，指数退避
- **帧间比对**：自动加入前一帧，用于区分"放网 vs 搓球"

**决策树**：
1. 一票否决（非击球动作：死球/准备/拣球/走动）
2. 发球识别（严格四项同时满足）
3. 击球识别（挥拍姿态，不过度要求球距）
4. 动作分类（前场/中场/后场/防守）
5. 技术评分（0-10分，五维度）
6. 错误诊断（E编号错误库）

**有效击球过滤**：白名单方式，`NON_SHOT_TYPES` 集合之外的所有动作类型都算有效击球。

### 报告生成（report_generator.py）

- 库：fpdf2（配合 Unicode 中文字体解决乱码）
- 字体：stheiti.ttf 华文细黑（TrueType Unicode），`add_font("STHeiti", fname=ASSETS_FONT, uni=True)`
- 图片宽高比：动态计算，宽度优先，高度按原始比例自适应（不变形）
- 卡片高度：文字超长时自动扩展（图文不重叠）
- 流程：`make_report(report_data, output_path)`
- 报告存档：两份（`reports/` + `~/Desktop/`）

### 球员档案（player_db.py）

- 目录：`~/Desktop/小程序/players/[球员名]/`
- `profile.json`：基本信息 + badges + sessions 摘要
- `history/YYYY-MM-DD.json`：每次分析完整数据
- 成就徽章系统：连续分析解锁徽章

---

## 质量标准（铁律）

### 逻辑一致性

> **动作还没发生，就不能有对应的技术诊断。**

- "准备发球"不能出现"闪腕/击球"分析
- 帧图与错误标签必须对得上
- 发现问题直接指出，不套话

### 报告视觉质量

- **图片比例不变形**：使用原图宽高比，不硬编码高度
- **图文不重叠**：图片与文字之间有足够间距
- **排版工整**：对齐、留白合理
- **每个动作都必须配图**：不丢图，有动作评判就要有对应帧图

### 商业原则

> **接单后必须出结果，不允许"分析结果不理想就跳过"。**

- 视频不合规格应在接单前拒绝
- 接了就要交付
- 微信推送默认自动进行

### GitHub

- GitHub TOKEN 不可用时 → 直接跳过，不阻塞主流程

### 术语偏好

- 用"准确度"代替"置信度"（更通俗易懂）

---

## API 配置

| 服务 | 用途 | 备注 |
|---|---|---|
| 硅基流动 | Qwen3-VL-32B-Instruct VLM | API Key 在 vlm_analyzer.py 头部 |
| 微信推送 | iLink 微信机器人 | o9cq8064W7qoIxddsBtaIBZAKQCk@im.wechat |

---

## 已知限制

1. **VLM 误判**：击球姿态帧可能被误判为"死球/拣球"
- [x] **击球检出率**：历史瓶颈（2fps），已升级为 4fps + 兜底规则
3. **球员识别**：当前依赖场上位置 + 制服颜色，无人脸识别
4. **无骨骼追踪**：当前方案为纯 VLM 视觉分析，无骨骼关键点数据

---

## 下一步计划（供接手参考）

- [x] Day 2：VLM prompt 调优 + 并发提速 + 缓存逻辑修复
- [x] VLM V1 锁定（V2 因 Stage1 过严导致有效击球 0 帧，已废弃）
- [x] 技术监理两层过滤（不确定性跳过 + 非击球帧清空）
- [x] Claude Code 全链路代码审查（2026-05-12）：发现 P0/P1 问题 6 个，已列入 W1D1~W1D3 执行计划
- [ ] W1D1（5月12日）：字体验证 + add_font修复 + 图片不变形修复
- [ ] W1D2（5月13日）：图文重叠修复 + V2球员字段修复
- [ ] W1D3（5月14日）：VLM解析健壮性（默认5分→0分）
- [ ] W1D4（5月15日）：全链路集成测试（关键里程碑）
- [ ] W1D5（5月16日）：压力测试 + 徽章验证
- [ ] W2D1~D2（5月19~20日）：真实视频验证 + 微信推送
- [ ] W2D3~D4（5月21~22日）：战术 prompt 调优
- [ ] W2D5（5月23日）：球员档案进步曲线验证
- [ ] W2D6~D7（5月24~25日）：部署上线
- [ ] 成就徽章系统完善
- [ ] 进步对比报告（含历史帧图并排）
- [ ] 小程序后端 API 设计
