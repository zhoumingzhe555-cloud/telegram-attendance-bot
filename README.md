# Telegram Attendance Bot - AI室排队 + TXT日报版

## 本版修复

修复 Telegram 报错：

```text
Message is too long
```

当日报内容太长时，机器人会自动生成 TXT 文件发送到群里。

## Railway 部署

上传以下文件到 GitHub 仓库：

- main.py
- requirements.txt
- Procfile
- README.md

Railway Variables 设置：

```text
TOKEN=你的Telegram Bot Token
```

## 群内文字

- `AI`：申请AI室；满了自动加入排队
- `AI室`：查看1号/2号/3号AI室占用情况
- `排队`：查看AI排队名单
- `取消排队`：退出AI排队
- `报表` / `日报` / `出勤表`：手动查看出勤表，太长会发TXT
- `1号AI室` / `2号AI室` / `3号AI室`：进入指定AI室
- `回`：返回工位，同时释放AI室并自动叫下一个排队人

## 命令

- `/chatid`：保存群ID
- `/testreport`：测试发送日报
- `/report`：手动发送日报

## 自动时间

- 03:00:05 自动发送日报
- 05:05:00 自动清空数据和AI队列
