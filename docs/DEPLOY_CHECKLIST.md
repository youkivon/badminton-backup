# 部署 Checklist

## 环境要求

| 项目 | 要求 | 验证命令 |
|------|------|---------|
| Python | >= 3.10 | `python3 --version` |
| ffmpeg | >= 4.0 | `ffmpeg -version \| head -1` |
| 系统字体缓存 | fc-cache | `fc-list :lang=zh \| head -3` |

## 依赖安装

```bash
pip install -r requirements.txt
```

### requirements.txt

```
fpdf2==2.8.7
reportlab==4.5.0
opencv-contrib-python==4.13.0.92
pillow==12.2.0
requests==2.34.0
edge-tts==7.2.8
pdf2image==1.17.0
pdfplumber==0.11.9
PyMuPDF==1.27.2.2
pypdfium2==5.7.1
pdfminer.six==20251230
chattts==0.2.5
neutts==1.2.1
```

## 字体部署

字体文件：**`stheiti.ttf`**（华文细黑，Unicode TrueType）

部署路径（二选一）：
- `src/assets/stheiti.ttf`（相对路径，代码默认）
- `/usr/local/share/fonts/stheiti.ttf`（系统级）

字体验证：
```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('STHeiti', 'stheiti.ttf'))
```

## 配置文件

```bash
# 环境变量或 config.json
SILICON_FLOW_API_KEY=sk-xxxxx
MINIMAX_API_KEY=xxxxx
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx
```

## 目录权限

| 目录 | 用途 | 最低权限 |
|------|------|---------|
| `/tmp/bad_shots/` | 帧提取 | 读+写+执行 |
| `assets/` | 字体/模板 | 只读 |
| `~/Downloads/` | PDF输出 | 读+写 |

## 端口和服务

| 服务 | 端口 | 依赖 |
|------|------|------|
| 微信推送 | 443 (HTTPS) | requests |
| 硅基流动API | 443 (HTTPS) | requests |

## 启动验证（audit）

```bash
cd src
python3 -c "
from run_analysis import SystemChecker
ch = SystemChecker().run_all()
print('PASS' if ch['passed_count'] == ch['total_count'] else 'FAIL')
print(ch)
"
```

预期：`passed_count == total_count`

## 快速测试

```bash
cd src
python3 run_analysis.py --video ../test_videos/video1.mp4 --player "测试球员"
```

预期：PDF生成成功 + 微信推送成功

---

*最后更新：2026-05-24 W2D6*
