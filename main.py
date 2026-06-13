import csv
import os
import threading
from datetime import datetime, time, timedelta, timezone

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# ==================== ⚙️ Railway 配置 ====================
# Railway → Variables 里设置：TOKEN=你的Bot Token
TOKEN = os.getenv("TOKEN")

# ==================== 📁 文件路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "work_records.csv")
CHAT_ID_FILE = os.path.join(BASE_DIR, "group_chat_id.txt")

# ==================== ⏰ 时间配置 ====================
TZ_CHINA = timezone(timedelta(hours=8))
WORK_START_TIME = time(9, 55, 0)
WORK_END_TIME = time(2, 0, 0)

# 03:00:05 自动发送日报，05:05 自动清空数据
DAILY_REPORT_TIME = time(3, 0, 5, tzinfo=TZ_CHINA)
AUTO_RESET_TIME = time(5, 5, 0, tzinfo=TZ_CHINA)

# ==================== 🚨 超时限制配置 ====================
TIMEOUT_LIMITS = {
    "wc小": 5,
    "wc大": 15,
    "吃饭": 30,
    "抽烟": 5
}

# ==================== 🤖 AI室配置 ====================
AI_ROOMS = ["1号AI室", "2号AI室", "3号AI室"]

# ==================== ✅ 有效打卡项目 ====================
VALID_ITEMS = {
    "上班": "🏁 开始工作",
    "wc小": "🚽 离开去洗手间(小)",
    "wc大": "💩 离开去洗手间(大)",
    "视频": "📹 离开去开视频/看视频",
    "开会": "🤝 进入会议/开会中",
    "吃饭": "🍱 离开去吃饭/就餐",
    "语音": "🎙️ 离开去发语音/听语音",
    "抽烟": "🚬 离开去抽烟",
    "AI": "🤖 查询AI室空位",
    "1号AI室": "🤖 进入 1号AI室 使用人工智能",
    "2号AI室": "🤖 进入 2号AI室 使用人工智能",
    "3号AI室": "🤖 进入 3号AI室 使用人工智能",
    "回": "🔙 已返回工位",
    "下班": "🌙 结束工作下班"
}

TRADITIONAL_MAP = {
    "上班": "上班",
    "吃飯": "吃饭",
    "語音": "语音",
    "開會": "开会",
    "下班": "下班",
    "抽煙": "抽烟",
    "視频": "视频",
    "視頻": "视频",
    "號AI室": "号AI室",
    "號ai室": "号AI室",
}

csv_lock = threading.Lock()
CURRENT_CHAT_ID = None


def init_csv_file():
    try:
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                "时间", "日期", "用户ID", "昵称",
                "动作项目", "当前项目累计次数", "考勤状态", "离开时长"
            ])
        print(f"✅ 已创建/重置考勤文件: {CSV_FILE}")
    except Exception as e:
        print(f"❌ 创建CSV失败: {e}")


def ensure_csv_exists():
    if not os.path.exists(CSV_FILE):
        init_csv_file()


def load_chat_id():
    global CURRENT_CHAT_ID

    if CURRENT_CHAT_ID:
        return CURRENT_CHAT_ID

    if os.path.exists(CHAT_ID_FILE):
        try:
            with open(CHAT_ID_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val.replace("-", "").isdigit():
                    CURRENT_CHAT_ID = int(val)
                    return CURRENT_CHAT_ID
        except Exception as e:
            print(f"❌ 读取群 chat_id 失败: {e}")

    return None


def save_chat_id(chat_id):
    global CURRENT_CHAT_ID
    CURRENT_CHAT_ID = chat_id

    try:
        with open(CHAT_ID_FILE, "w", encoding="utf-8") as f:
            f.write(str(chat_id))
        print(f"✅ 已保存群 chat_id: {chat_id}")
    except Exception as e:
        print(f"❌ 保存群 chat_id 失败: {e}")


def get_business_date(dt):
    if dt.time() < time(3, 0, 0):
        return (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def normalize_text(raw_text):
    text = raw_text.strip()

    for trad, simp in TRADITIONAL_MAP.items():
        if trad in text:
            text = text.replace(trad, simp)

    low = text.lower()
    if low == "ai" or low.startswith("ai "):
        return "AI"

    compact = text.replace(" ", "").replace("　", "")
    low_compact = compact.lower()

    if low_compact in ["1号ai室", "1号ai", "一号ai室", "一号ai"]:
        return "1号AI室"
    if low_compact in ["2号ai室", "2号ai", "二号ai室", "二号ai"]:
        return "2号AI室"
    if low_compact in ["3号ai室", "3号ai", "三号ai室", "三号ai"]:
        return "3号AI室"

    return text


ensure_csv_exists()
load_chat_id()


def get_today_action_count(user_id, action, biz_date_str):
    count = 0
    with csv_lock:
        ensure_csv_exists()
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if row and len(row) >= 5:
                    if str(row[1]) == str(biz_date_str) and str(row[2]) == str(user_id) and str(row[4]) == str(action):
                        count += 1
    return count


def get_last_leave_record(user_id):
    leave_actions = set(TIMEOUT_LIMITS.keys()) | {"开会", "视频", "语音"} | set(AI_ROOMS)

    with csv_lock:
        ensure_csv_exists()
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))

        for row in reversed(rows):
            if not row or len(row) < 5:
                continue

            if str(row[2]) != str(user_id):
                continue

            if row[4] in ["回", "上班", "下班"]:
                return None, None

            if row[4] in leave_actions:
                return row[4], row[0]

    return None, None


def get_active_ai_rooms():
    active_rooms = {}

    with csv_lock:
        ensure_csv_exists()
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)

            for row in reader:
                if not row or len(row) < 5:
                    continue

                uid = str(row[2])
                name = row[3]
                action = row[4]

                if action in AI_ROOMS:
                    for room, info in list(active_rooms.items()):
                        if info["uid"] == uid:
                            active_rooms.pop(room, None)

                    active_rooms[action] = {"uid": uid, "name": name}

                elif action in ["回", "下班"]:
                    for room, info in list(active_rooms.items()):
                        if info["uid"] == uid:
                            active_rooms.pop(room, None)

    return active_rooms


def get_ai_room_tip_text():
    active_rooms = get_active_ai_rooms()
    free_rooms = [room for room in AI_ROOMS if room not in active_rooms]

    if active_rooms:
        used_text = "、".join([f"{room}（{info['name']}使用中）" for room, info in active_rooms.items()])
    else:
        used_text = "暂无占用"

    if free_rooms:
        return (
            f"🤖 <b>AI室使用提醒</b>\n\n"
            f"🚫 已占用：{used_text}\n"
            f"✅ 可使用：<b>{'、'.join(free_rooms)}</b>\n\n"
            f"请发送具体房间，例如：<b>{free_rooms[0]}</b>"
        )

    return (
        f"🤖 <b>AI室使用提醒</b>\n\n"
        f"🚫 已占用：{used_text}\n"
        f"❌ 当前 1号AI室、2号AI室、3号AI室 都已被占用，请稍后再使用。"
    )


def generate_report_text():
    now_dt = datetime.now(TZ_CHINA)
    biz_date_str = get_business_date(now_dt)

    user_summary = {}
    user_last_action = {}

    with csv_lock:
        ensure_csv_exists()

        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)

            for row in reader:
                if not row or len(row) < 8 or row[1] != biz_date_str:
                    continue

                uid, name, action, status, duration = row[2], row[3], row[4], row[6], row[7]
                time_part = row[0].split(" ")[1][:5] if " " in row[0] else row[0][:5]

                if uid not in user_summary:
                    user_summary[uid] = {
                        "name": name,
                        "上班": "❌ 未打卡",
                        "下班": "❌ 未打卡",
                        "actions": {}
                    }

                if action == "上班":
                    user_summary[uid]["上班"] = f"✅ {time_part} ({status})"
                    user_last_action[uid] = None

                elif action == "下班":
                    user_summary[uid]["下班"] = f"✅ {time_part} ({status})"
                    user_last_action[uid] = None

                elif action != "回" and action != "AI":
                    if action not in user_summary[uid]["actions"]:
                        user_summary[uid]["actions"][action] = {"count": 0, "mins": 0}
                    user_summary[uid]["actions"][action]["count"] += 1
                    user_last_action[uid] = action

                elif action == "回":
                    last_act = user_last_action.get(uid)
                    if last_act and "分" in duration and last_act in user_summary[uid]["actions"]:
                        try:
                            mins = int(duration.split("分")[0])
                            user_summary[uid]["actions"][last_act]["mins"] += mins
                        except Exception:
                            pass
                    user_last_action[uid] = None

    if not user_summary:
        return f"📋 全员出勤总榜单 ({biz_date_str})\n━━━━━━━━━━━━━━━━━━\n\nℹ️ 暂无任何打卡数据。"

    report_text = f"📋 全员出勤总榜单 ({biz_date_str})\n━━━━━━━━━━━━━━━━━━\n\n"

    for uid, data in user_summary.items():
        report_text += (
            f"👤 人员：{data['name']}\n"
            f" ├ ⏳ 上班状态： {data['上班']}\n"
            f" ├ 🌙 下班状态： {data['下班']}\n"
        )

        leave_details = []
        for act_name, act_info in data["actions"].items():
            icon = "📊"
            for k, v in VALID_ITEMS.items():
                if k in act_name:
                    icon = v.split(" ")[0]
                    break

            if act_info["mins"] > 0:
                leave_details.append(f"{icon}{act_name} {act_info['count']}次 (累计 {act_info['mins']} 分钟)")
            else:
                leave_details.append(f"{icon}{act_name} {act_info['count']}次")

        detail_text = "、".join(leave_details) if leave_details else "正常在岗，无离岗记录"

        report_text += f" └ 📝 出勤细节： {detail_text}\n──────────────────\n"

    return report_text


async def timeout_alert(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    alert_text = (
        f"🚨 <b>【超时严重警告】</b> 🚨\n\n"
        f"👤 <a href='tg://user?id={d['user_id']}'>{d['full_name']}</a> "
        f"登记为 [<b>{d['action']}</b>]\n"
        f"⚠️ 规定的 <b>{d['minutes']}</b> 分钟时限已过！\n\n"
        f"📢 <b>您已严重超时，请准备接受惩罚！</b> 💀"
    )

    try:
        await context.bot.send_message(chat_id=d["chat_id"], text=alert_text, parse_mode="HTML")
    except Exception as e:
        print(f"❌ 发送超时报警失败: {e}")


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_chat_id()

    if not chat_id:
        print("❌ 没有找到群 chat_id，无法自动发送下班统计。请先在群里发送 /chatid")
        return

    try:
        await context.bot.send_message(chat_id=chat_id, text=generate_report_text(), parse_mode="HTML")
        print("✅ 下班统计报表已自动发送")
    except Exception as e:
        print(f"❌ 自动发送下班统计失败: {e}")


async def auto_reset_csv_job(context: ContextTypes.DEFAULT_TYPE):
    with csv_lock:
        init_csv_file()
        print("⏰ 新班次开始，CSV数据已安全重置。")


async def manual_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            generate_report_text() + "\n💡 <i>提示：此报表由管理员手动调用生成。</i>",
            parse_mode="HTML"
        )


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        save_chat_id(update.message.chat_id)
        await update.message.reply_text(
            f"✅ 当前群 chat_id 已保存：\n<code>{update.message.chat_id}</code>",
            parse_mode="HTML"
        )


async def test_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        save_chat_id(update.message.chat_id)
        await daily_report_job(context)


async def airooms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(get_ai_room_tip_text(), parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user:
        return

    user = update.effective_user
    chat_id = update.message.chat_id
    raw_text = update.message.text.strip()

    print("收到消息:", raw_text)

    normalized_text = normalize_text(raw_text)

    # 用户只发 AI：不登记，只提醒空AI室
    if normalized_text == "AI":
        save_chat_id(chat_id)
        await update.message.reply_text(get_ai_room_tip_text(), parse_mode="HTML")
        return

    user_text = None
    lower_raw = normalized_text.lower()

    for item in VALID_ITEMS:
        if lower_raw.startswith(item.lower()):
            user_text = item
            break

    if user_text not in VALID_ITEMS or user_text == "AI":
        return

    # 报备具体AI室时，检查是否被别人占用
    if user_text in AI_ROOMS:
        active_rooms = get_active_ai_rooms()

        if user_text in active_rooms and active_rooms[user_text]["uid"] != str(user.id):
            free_rooms = [room for room in AI_ROOMS if room not in active_rooms]

            if free_rooms:
                await update.message.reply_text(
                    f"⚠️ <b>{user_text}</b> 已被 <b>{active_rooms[user_text]['name']}</b> 使用中。\n"
                    f"✅ 请去：<b>{'、'.join(free_rooms)}</b>",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>{user_text}</b> 已被 <b>{active_rooms[user_text]['name']}</b> 使用中。\n"
                    f"当前三个AI室都已被占用，请稍后再使用。",
                    parse_mode="HTML"
                )
            return

    save_chat_id(chat_id)

    now_dt = datetime.now(TZ_CHINA)
    biz_date_str = get_business_date(now_dt)
    current_time = now_dt.time()

    status_note = "正常"

    if user_text == "上班":
        if current_time > WORK_START_TIME or current_time < WORK_END_TIME:
            status_note = "⚠️ 迟到"

    if user_text == "下班":
        if current_time < WORK_END_TIME and current_time > time(3, 0, 0):
            status_note = "⚠️ 早退"

    job_id = f"timeout_{user.id}"
    for job in context.job_queue.get_jobs_by_name(job_id):
        job.schedule_removal()

    duration_report = ""
    duration_str_to_save = "N/A"

    if user_text == "回":
        last_act, last_time_str = get_last_leave_record(user.id)

        if last_time_str:
            try:
                last_dt = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_CHINA)
                diff = now_dt - last_dt
                total_seconds = int(diff.total_seconds())
                mins = total_seconds // 60
                secs = total_seconds % 60

                duration_report = (
                    f"⏱️ <b>本次 [{last_act}] 共计离开：</b> "
                    f"<b>{mins}</b> 分 <b>{secs}</b> 秒\n"
                )
                duration_str_to_save = f"{mins}分{secs}秒"
            except Exception as e:
                duration_report = f"⚠️ 离开时长计算失败：{e}\n"
        else:
            duration_report = "ℹ️ 未找到离开记录。\n"

    if user_text in TIMEOUT_LIMITS:
        limit = TIMEOUT_LIMITS[user_text]
        context.job_queue.run_once(
            timeout_alert,
            when=timedelta(minutes=limit),
            name=job_id,
            data={
                "chat_id": chat_id,
                "user_id": user.id,
                "full_name": user.full_name,
                "action": user_text,
                "minutes": limit
            }
        )

    full_name = user.full_name if user.full_name else f"User_{user.id}"
    past_count = get_today_action_count(user.id, user_text, biz_date_str) + 1

    try:
        with csv_lock:
            with open(CSV_FILE, mode="a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow([
                    now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    biz_date_str,
                    user.id,
                    full_name,
                    user_text,
                    past_count,
                    status_note,
                    duration_str_to_save
                ])

    except PermissionError:
        await update.message.reply_text(
            "❌ 无法写入考勤文件，请关闭 Excel 或其他正在打开 work_records.csv 的程序。"
        )
        return

    except Exception as e:
        await update.message.reply_text(f"❌ 文件写入失败：{e}")
        return

    reply_msg = (
        f"<b>{VALID_ITEMS[user_text]} 登记成功！</b>\n"
        f"⏰ <b>时间：</b> {now_dt.strftime('%H:%M:%S')}\n"
    )

    if user_text in AI_ROOMS:
        active_rooms = get_active_ai_rooms()
        free_rooms = [room for room in AI_ROOMS if room not in active_rooms]
        if free_rooms:
            reply_msg += f"✅ 剩余可用AI室：{'、'.join(free_rooms)}\n"
        else:
            reply_msg += "⚠️ 当前三个AI室已全部占用。\n"

    if duration_report:
        reply_msg += duration_report
    else:
        reply_msg += f"🔢 <b>今日该项累计：</b> {past_count} 次\n"

        if status_note != "正常":
            reply_msg += f"📢 <b>考勤提醒：</b> {status_note}\n"

    await update.message.reply_text(reply_msg, parse_mode="HTML")


def main():
    if not TOKEN:
        print("❌ 没有读取到 TOKEN 环境变量")
        print("Railway 请在 Variables 设置：TOKEN=你的BotToken")
        return

    print("✅ 已读取到 TOKEN")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("report", manual_report_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("testreport", test_report_command))
    application.add_handler(CommandHandler("airooms", airooms_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = application.job_queue

    if job_queue is None:
        print('❌ JobQueue 未启用。请安装：pip install "python-telegram-bot[job-queue]"')
        return

    job_queue.run_daily(daily_report_job, time=DAILY_REPORT_TIME, name="daily_report_job")
    job_queue.run_daily(auto_reset_csv_job, time=AUTO_RESET_TIME, name="auto_reset_csv_job")

    print("✅ 考勤机器人已启动")
    print(f"📊 自动下班统计时间：{DAILY_REPORT_TIME}")
    print(f"🧹 自动清空CSV时间：{AUTO_RESET_TIME}")
    print("💡 群里发送 /chatid 保存群ID")
    print("💡 群里发送 /testreport 测试自动报表")
    print("💡 群里发送 /airooms 查看AI室占用情况")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
