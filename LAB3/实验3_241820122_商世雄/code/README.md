# 泊岸酒店预订系统

Python + Tkinter + SQLite 桌面程序。游客可查房，顾客管理本人预订，酒店人员管理本酒店业务，管理员审核酒店与处理异常。

## 1. 运行

### Windows便携版（无需安装Python）

打开 `dist/StayHotel/StayHotel.exe`。必须保留旁边的 `_internal` 目录，不要只复制exe。

### 源码运行

需要 Python 3.11 或更高版本，安装时勾选 Tcl/Tk。建议使用本次验证过的 Python 3.12。

在当前 `code` 目录打开终端：

```powershell
python -m pip install -r requirements.txt
python run.py
```

也可双击 `启动程序.cmd`。不需要安装数据库服务器或连接网络；首次安装依赖时需要网络。

首次打开空数据库时，系统初始化两家南京酒店、三种房型及从当天开始60天的日历。已有数据库不会重置；如果演示数据过期，登录酒店账号重新设置日历，不要删除真实业务数据库。

| 账号 | 密码 | 身份 |
| --- | --- | --- |
| customer | Guest2026! | 顾客 |
| customer2 | Guest2026! | 第二位顾客，验证权限隔离 |
| staff | Staff2026! | 南京泊岸酒店工作人员 |
| staff2 | Staff2026! | 秦淮栖居酒店工作人员 |
| admin | Admin2026! | 平台管理员 |

以上仅供本地课程演示；保存实际信息前请用右上角“修改密码”更换密码。改密码会注销该账号的全部旧会话。

默认数据库：`%LOCALAPPDATA%\StayHotel\stay.sqlite3`。运行日志及备份保存在同一目录。测试数据和日常数据库彼此隔离。指定另一份数据：

```powershell
python run.py --db "D:\HotelDemo\stay.sqlite3"
```

## 2. 主要功能与规则

- 城市、日期、人数、间数、房型和全程单间价格组合查询；可查看逐夜报价。
- 顾客注册、登录、改密码；创建、修改、取消本人订单，查看成交明细及历史。
- 酒店人员维护房型与日历，确认、拒绝、核验入住和正常退房。
- 管理员审核启停酒店、创建停用工作人员、逐笔异常取消；通知待办、统计、日志及数据诊断。
- 住宿区间按 `[入住, 离店)` 计算，金额以整数分存储，保留逐夜成交价。
- 待确认订单预留库存；酒店确认、入住不再次扣房。30分钟严格到期，恰好到期也不能确认或修改。
- 待确认可改住宿；已确认只能改联系人。顾客取消已确认订单须早于酒店当地入住日18:00。
- 未入住判定为酒店当地入住日次日00:00；仅释放未消费的房量。正常退房不回补历史房量。
- 停售日期不能增加占用，但可保持或减少；酒店停业后禁止新订和住宿方案修改。
- 同一请求键与内容重试返回原结果；旧版本修改拒绝。SQLite写事务保证全程库存更新与订单写入原子性。

更详细的操作步骤见 `docs/验收操作.md`，设计映射和差异见 `docs/实现映射与差异.md`。

## 3. 测试和代码规范

```powershell
python -m pip install -r requirements-dev.txt
python scripts/verify.py
```

原始结果保存在 `evidence/`，包括退出码、JUnit结果、覆盖率、Ruff、Pylint和源码自检。完整测试包含真实Tk控件，所以需要桌面图形环境。自动化GUI测试会自动处理测试对话框，并非用户可用性测试。

只运行源码业务自检（不改日常数据库）：

```powershell
python run.py --self-test --output evidence/source-self-test.json
```

大数据量本机性能检查另行运行，建议不要同时构建或运行其他压测：

```powershell
python scripts/benchmark.py
```

该脚本临时建立10000家酒店、50000房型、100000条订单和1500000条日历；20并发各100次查询/预订，保留全部样本。数据初始化和一致性检查耗时较长，需要约1GB临时可用空间，运行结束自动删除隔离数据库。结果是本地服务调用耗时，不是HTTP请求耗时，也不代表LAB2规划的服务器环境达标。

## 4. 构建

```powershell
python scripts/build.py
```

- `dist/stay_hotel-1.0.0-py3-none-any.whl`：可安装包。
- `dist/stay_hotel-1.0.0.tar.gz`：源码发行包。
- `dist/StayHotel/`：Windows便携程序及运行库。
- `evidence/build.json`：构建步骤退出码；`frozen-self-test.json`为真正执行exe后的结果。

使用PyInstaller目录模式而非单文件模式，减少解压启动时间，并显式携带Tk及Windows时区数据。可执行文件只适用于对应的Windows x64平台。

UML重导出需要Java和PlantUML jar：

```powershell
python scripts/render_uml.py --jar "D:\tools\plantuml-1.2025.10.jar"
```

`scripts/capture.py` 使用隔离数据启动真实Tk窗口并截取九张界面图，截图保存到上级 `运行材料/界面截图/`，不是HTML原型图。

## 5. 备份与恢复

管理员“数据检查与备份”页面可以立即备份和诊断；程序运行期间后台每24小时执行一次自动备份，关闭程序时后台任务也停止。手工备份同时输出SHA256及一致性清单。

先关闭日常程序，再恢复到一个不存在的新文件：

```powershell
python run.py --restore "D:\backup\stay-20261114-xxxx.sqlite3" --destination "D:\recovered\stay.sqlite3"
python run.py --db "D:\recovered\stay.sqlite3"
```

恢复入口拒绝覆盖已有文件，并检查数据库版本、外键、库存及价格合计。保留原库，核对恢复结果后再决定使用哪份数据库。

## 6. 目录

```text
src/stay/       领域、业务服务、数据库和手写Tk界面
tests/          业务、边界、权限、并发、恢复、CLI及GUI测试
scripts/        验证、统计、构建、压测、UML导出和截图脚本
docs/           UML映射、实现差异、操作及修订记录
evidence/       实际运行日志和结构化结果
dist/           本机构建产物，不纳入Git
```

## 7. 范围与限制

这是本地单进程桌面实现，不含Web/移动端、支付退款、短信、房号分配、清洁维修、提前/延迟入住、提前退房和续住。查询和部分列表上限为200条；订单和日志服务支持offset，但界面未提供完整分页。跨主机、多实例部署不在本次范围。

会话、数据库权限和并发检查在业务入口执行，不只是隐藏按钮。SQLite文件属于操作系统登录用户，无法防止拥有本机文件读写权限的人直接篡改文件，不能当作公网生产系统。
