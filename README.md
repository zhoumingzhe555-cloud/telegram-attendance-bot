# Telegram Attendance Bot - AI室排队版

## Railway 部署

1. 把 `main.py`、`requirements.txt`、`Procfile` 上传到 GitHub 仓库。
2. Railway 连接 GitHub 仓库。
3. Railway → Variables 新增：

```text
TOKEN=你的Telegram Bot Token
```

4. 部署成功后，群里发送：

```text
/chatid
```

保存群ID。

## 群内文字

- `AI`：申请AI室；如果满了，自动加入排队
- `AI室`：查看1号/2号/3号AI室占用情况
- `排队`：查看当前AI排队名单
- `取消排队`：退出AI排队
- `1号AI室` / `2号AI室` / `3号AI室`：进入指定AI室
- `回`：返回工位，同时释放AI室并自动叫下一个排队人

## 自动时间

- 03:00:05 自动发送日报
- 05:05:00 自动清空数据和AI队列
