import csv
import os
import json
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
QUEUE_FILE = os.path.join(BASE_DIR, "ai_queue.json")

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
    "AI": "🤖 申请AI室",
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
queue_lock = threading.Lock()
CURRENT_CHAT_ID = None


# ==================== 📌 基础工具函数 ====================
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
    # 凌晨 03:00 前算前一天班次
    if dt.time() < time(3, 0, 0):
        return (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def normalize_text(raw_text):
    text = raw_text.strip()
    for trad, simp in TRADITIONAL_MAP.items():
        if trad in text:
            text = text.replace(trad, simp)

    compact = text.replace(" ", "").replace("　", "")
    low_compact = compact.lower()

    if low_compact in ["ai", "申请ai", "排ai", "我要ai"]:
        return "AI"

    if compact in ["AI室", "ai室", "Ai室", "aI室", "房间", "房間"]:
        return "AI室"

    if compact in ["排队", "排隊", "队列", "隊列", "AI排队", "ai排队"]:
        return "排队"

    if compact in ["取消排队", "取消排隊", "退出排队", "退出排隊", "不排了"]:
        return "取消排队"

    if low_compact in ["1号ai室", "1号ai", "一号ai室", "一号ai"]:
        return "1号AI室"
    if low_compact in ["2号ai室", "2号ai", "二号ai室", "二号ai"]:
        return "2号AI室"
    if low_compact in ["3号ai室", "3号ai", "三号ai室", "三号ai"]:
        return "3号AI室"

    return text


def mention_user(user_id, name):
    safe_name = name or "用户"
    return f"<a href='tg://user?id={user_id}'>{safe_name}</a>"


ensure_csv_exists()
load_chat_id()


# ==================== 🤖 AI排队文件 ====================
def load_ai_queue():
    with queue_lock:
        if not os.path.exists(QUEUE_FILE):
            return []
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []


def save_ai_queue(queue):
    with queue_lock:
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ 保存AI队列失败: {e}")


def add_to_ai_queue(user_id, name):
    queue = load_ai_queue()
    uid = str(user_id)

    for index, item in enumerate(queue, start=1):
        if str(item.get("uid")) == uid:
            return False, index

    queue.append({
        "uid": uid,
        "name": name,
        "time": datetime.now(TZ_CHINA).strftime("%Y-%m-%d %H:%M:%S")
    })
    save_ai_queue(queue)
    return True, len(queue)


def remove_from_ai_queue(user_id):
    queue = load_ai_queue()
    uid = str(user_id)
    new_queue = [item for item in queue if str(item.get("uid")) != uid]
    changed = len(new_queue) != len(queue)
    if changed:
        save_ai_queue(new_queue)
    return changed


def pop_next_ai_queue():
    queue = load_ai_queue()
    if not queue:
        return None
    next_user = queue.pop(0)
    save_ai_queue(queue)
    return next_user


def get_ai_queue_text():
    queue = load_ai_queue()
    if not queue:
        return "📋 <b>AI排队名单</b>\n\n✅ 当前无人排队。"

    text = "📋 <b>AI排队名单</b>\n\n"
    for i, item in enumerate(queue, start=1):
        text += f"{i}. {mention_user(item.get('uid'), item.get('name'))}\n"
    return text


# ==================== 📊 CSV读取/统计 ====================
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


def get_ai_room_status_text():
    active_rooms = get_active_ai_rooms()
    lines = ["🤖 <b>AI室状态</b>\n"]

    for room in AI_ROOMS:
        if room in active_rooms:
            info = active_rooms[room]
            lines.append(f"{room}：🚫 {mention_user(info['uid'], info['name'])} 使用中")
        else:
            lines.append(f"{room}：✅ 空闲")

    free_rooms = [room for room in AI_ROOMS if room not in active_rooms]
    if free_rooms:
        lines.append(f"\n✅ 可用：<b>{'、'.join(free_rooms)}</b>")
    else:
        lines.append("\n❌ 当前三个AI室都已占用。")

    queue = load_ai_queue()
    lines.append(f"📋 当前排队人数：<b>{len(queue)}</b>")

    return "\n".join(lines)


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


# ==================== 🚨 超时提醒 ====================
async def timeout_alert(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    alert_text = (
        f"🚨 <b>【超时严重警告】</b> 🚨\n\n"
        f"👤 {mention_user(d['user_id'], d['full_name'])} 登记为 [<b>{d['action']}</b>]\n"
        f"⚠️ 规定的 <b>{d['minutes']}</b> 分钟时限已过！\n\n"
        f"📢 <b>您已严重超时，请准备接受惩罚！</b> 💀"
    )

    try:
        await context.bot.send_message(chat_id=d["chat_id"], text=alert_text, parse_mode="HTML")
    except Exception as e:
        print(f"❌ 发送超时报警失败: {e}")


async def notify_next_queue_user(context, chat_id, room):
    next_user = pop_next_ai_queue()
    if not next_user:
        return

    text = (
        f"📢 <b>AI室排队叫号</b>\n\n"
        f"<b>{room}</b> 已空出。\n"
        f"请 {mention_user(next_user['uid'], next_user['name'])} 去 <b>{room}</b>。\n\n"
        f"请发送：<b>{room}</b> 正式登记。"
    )

    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"❌ 发送AI叫号失败: {e}")


# ==================== ⏰ 自动任务 ====================
async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_chat_id()

    if not chat_id:
        print("❌ 没有找到群 chat_id，无法自动发送下班统计。请先在群里发送：chatid 或 /chatid")
        return

    try:
        await context.bot.send_message(chat_id=chat_id, text=generate_report_text(), parse_mode="HTML")
        print("✅ 下班统计报表已自动发送")
    except Exception as e:
        print(f"❌ 自动发送下班统计失败: {e}")


async def auto_reset_csv_job(context: ContextTypes.DEFAULT_TYPE):
    with csv_lock:
        init_csv_file()
        save_ai_queue([])
        print("⏰ 新班次开始，CSV数据和AI队列已安全重置。")


# ==================== 🧾 命令 / 文字兼容 ====================
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


# ==================== 💬 消息处理 ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user:
        return

    user = update.effective_user
    chat_id = update.message.chat_id
    raw_text = update.message.text.strip()
    normalized_text = normalize_text(raw_text)

    print("收到消息:", raw_text)

    # 保存群ID
    if normalized_text in ["chatid", "群id", "保存群id"]:
        save_chat_id(chat_id)
        await update.message.reply_text(
            f"✅ 当前群 chat_id 已保存：\n<code>{chat_id}</code>",
            parse_mode="HTML"
        )
        return

    # 查看AI室
    if normalized_text == "AI室":
        save_chat_id(chat_id)
        await update.message.reply_text(get_ai_room_status_text(), parse_mode="HTML")
        return

    # 查看排队
    if normalized_text == "排队":
        save_chat_id(chat_id)
        await update.message.reply_text(get_ai_queue_text(), parse_mode="HTML")
        return

    # 取消排队
    if normalized_text == "取消排队":
        save_chat_id(chat_id)
        removed = remove_from_ai_queue(user.id)
        if removed:
            await update.message.reply_text("✅ 已退出AI排队队列。")
        else:
            await update.message.reply_text("ℹ️ 你当前不在AI排队队列中。")
        return

    # 用户发 AI：有空房就提示；没空房就自动排队
    if normalized_text == "AI":
        save_chat_id(chat_id)
        active_rooms = get_active_ai_rooms()
        free_rooms = [room for room in AI_ROOMS if room not in active_rooms]

        if free_rooms:
            await update.message.reply_text(
                f"🤖 <b>AI室申请</b>\n\n"
                f"{get_ai_room_status_text()}\n\n"
                f"请发送具体房间，例如：<b>{free_rooms[0]}</b>",
                parse_mode="HTML"
            )
        else:
            added, position = add_to_ai_queue(user.id, user.full_name)
            if added:
                await update.message.reply_text(
                    f"🤖 当前三个AI室都已满。\n\n"
                    f"✅ 已为你加入AI排队。\n"
                    f"📌 当前排队第 <b>{position}</b> 位。\n\n"
                    f"发送 <b>排队</b> 可查看队列。\n"
                    f"发送 <b>取消排队</b> 可退出队列。",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ 你已经在AI排队队列中。\n"
                    f"📌 当前排队第 <b>{position}</b> 位。",
                    parse_mode="HTML"
                )
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
                added, position = add_to_ai_queue(user.id, user.full_name)
                if added:
                    await update.message.reply_text(
                        f"❌ <b>{user_text}</b> 已被 <b>{active_rooms[user_text]['name']}</b> 使用中。\n"
                        f"当前三个AI室都已占用。\n\n"
                        f"✅ 已为你加入AI排队，第 <b>{position}</b> 位。",
                        parse_mode="HTML"
                    )
                else:
                    await update.message.reply_text(
                        f"❌ <b>{user_text}</b> 已被 <b>{active_rooms[user_text]['name']}</b> 使用中。\n"
                        f"你已在AI排队中。",
                        parse_mode="HTML"
                    )
            return

        # 进入具体AI室后，如果他原本在队列里，则移除
        remove_from_ai_queue(user.id)

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

    # 记录回之前，先看看他是不是从哪个AI室释放出来
    released_ai_room = None
    if user_text in ["回", "下班"]:
        active_before = get_active_ai_rooms()
        for room, info in active_before.items():
            if info["uid"] == str(user.id):
                released_ai_room = room
                break

    # 取消当前用户之前的超时提醒
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

    # 如果释放了AI室，自动叫下一个排队人
    if released_ai_room:
        await notify_next_queue_user(context, chat_id, released_ai_room)


# ==================== 🚀 主程序 ====================
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

    # 普通文字处理
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
    print("💡 群里发送：AI / AI室 / 排队 / 取消排队")
    print("💡 群里发送：/chatid 保存群ID")
    print("💡 群里发送：/testreport 测试自动报表")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
