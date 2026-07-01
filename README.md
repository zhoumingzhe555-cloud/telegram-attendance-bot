# Telegram 考勤机器人 企业版 V5

默认规则：
- 上班：09:55
- 下班：02:00
- 日报：03:00
- 清空：05:05
- AI室：1号AI室 到 5号AI室
- 离岗合计限制：wc小 + wc大 + 抽烟 合计 5 次
- 报表太长自动发送 TXT 文件
- 多群独立配置

群内普通文字：AI / AI室 / 排队 / 取消排队 / 报表 / 配置 / 菜单

管理命令：
/chatid
/config
/menu
/testreport
/setstart 09:55
/setend 02:00
/setreport 03:00
/setreset 05:05
/setrooms 5
/addroom 6号AI室
/delroom 5号AI室
/additem 培训 📚 进入培训
/delitem 培训
/settimeout 吃饭 30
/limit wc大 3
/limitgroup 离岗 5 wc小 wc大 抽烟
