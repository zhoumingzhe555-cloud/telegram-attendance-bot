import csv
import os
import threading
from datetime import datetime, time, timedelta, timezone

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# ==================== ⚙️ 机器人核心配置 ====================
TOKEN = os.getenv("TOKEN")

# ==================== 📁 文件路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "work_records.csv")
CHAT_ID_FILE = os.path.join(BASE_DIR, "group_chat_id.txt")

# ==================== ⏰ 时间配置 ====================
TZ_CHINA = timezone(timedelta(hours=8))
WORK_START_TIME = time(9, 55, 0)
WORK_END_TIME = time(2, 0, 0)
DAILY_REPORT_TIME = time(3, 0, 5, tzinfo=TZ_CHINA)
AUTO_RESET_TIME = time(5, 5, 0, tzinfo=TZ_CHINA)

# ==================== 🚨 超时限制配置 ====================
TIMEOUT_LIMITS = {
    "wc小": 5,
    "wc大": 15,
    "吃饭": 30,
    "抽烟": 5
}

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
    "1号AI室": "🤖 进入 1号AI室 使用人工智能",
    "2号AI室": "🤖 进入 2号AI室 使用人工智能",
    "3号AI室": "🤖 进入 3号AI室 使用人工智能",
    "回": "🔙 已返回工位",
    "下班": "🌙 结束工作下班"
}

AI_ROOMS = ["1号AI室", "2号AI室", "3号AI室"]

TRADITIONAL_MAP = {
    "上班": "上班", "吃飯": "吃饭", "語音": "语音", "開會": "开会",
    "下班": "下班", "抽煙": "抽烟", "視频": "视频", "視頻": "视频"
}

csv_lock = threading.Lock()
CURRENT_CHAT_ID = None


# ==================== 📌 基础工具函数 ====================
def init_csv_file():
    try:
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["时间", "日期", "用户ID", "昵称", "动作项目", "当前项目累计次数", "考勤状态", "离开时长"])
        print(f"✅ 已创建/重置考勤文件: {CSV_FILE}")
    except Exception as e:
        print(f"❌ 创建CSV失败: {e}")

def load_chat_id():
    global CURRENT_CHAT_ID
    if CURRENT_CHAT_ID: return CURRENT_CHAT_ID
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

def ensure_csv_exists():
    if not os.path.exists(CSV_FILE):
        init_csv_file()

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
            if row and len(row) >= 5:
                if str(row[2]) == str(user_id):
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
                if not row or len(row) < 5: continue
                name, action = row[3], row[4]
                if action in AI_ROOMS:
                    active_rooms[action] = name
                elif action in ["回", "上班", "下班"]:
                    for rm, occup_name in list(active_rooms.items()):
                        if occup_name == name:
                            active_rooms.pop(rm, None)
    return active_rooms


# ==================== 📊 报表生成 ====================
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
                if not row or len(row) < 8 or row[1] != biz_date_str: continue
                uid, name, action, status, duration = row[2], row[3], row[4], row[6], row[7]
                time_part = row[0].split(" ")[1][:5] if " " in row[0] else row[0][:5]

                if uid not in user_summary:
                    user_summary[uid] = {"name": name, "上班": "❌ 未打卡", "下班": "❌ 未打卡", "actions": {}}

                if action == "上班":
                    user_summary[uid]["上班"] = f"✅ {time_part} ({status})"
                    user_last_action[uid] = None
                elif action == "下班":
                    user_summary[uid]["下班"] = f"✅ {time_part} ({status})"
                    user_last_action[uid] = None
                elif action != "回":
                    if action not in user_summary[uid]["actions"]:
                        user_summary[uid]["actions"][action] = {"count": 0, "mins": 0}
                    user_summary[uid]["actions"][action]["count"] += 1
                    user_last_action[uid] = action
                else:
                    last_act = user_last_action.get(uid)
                    if last_act and "分" in duration and last_act in user_summary[uid]["actions"]:
                        try:
                            user_summary[uid]["actions"][last_act]["mins"] += int(duration.split("分")[0])
                        except Exception: pass
                    user_last_action[uid] = None

    if not user_summary:
        return f"📋 全员出勤总榜单 ({biz_date_str})\n━━━━━━━━━━━━━━━━━━\n\nℹ️ 暂无任何打卡数据。"

    report_text = f"📋 全员出勤总榜单 ({biz_date_str})\n━━━━━━━━━━━━━━━━━━\n\n"
    for uid, data in user_summary.items():
        report_text += f"👤 人员：{data['name']}\n ├ ⏳ 上班状态： {data['上班']}\n ├ 🌙 下班状态： {data['下班']}\n"
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
    alert_text = f"🚨 <b>【超时严重警告】</b> 🚨\n\n👤 <a href='tg://user?id={d['user_id']}'>{d['full_name']}</a> 登记为 [<b>{d['action']}</b>]\n⚠️ 规定的 <b>{d['minutes']}</b> 分钟时限已过！\n\n📢 <b>您已严重超时，请准备接受惩罚！</b> 💀"
    try:
        await context.bot.send_message(chat_id=d["chat_id"], text=alert_text, parse_mode="HTML")
    except Exception as e: print(f"❌ 发送超时报警失败: {e}")


# ==================== ⏰ 自动任务 ====================
async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_chat_id()
    if not chat_id:
        print("❌ 没有找到群 chat_id，无法自动发送下班统计。")
        return
    try:
        report = generate_report_text()
        await context.bot.send_message(chat_id=chat_id, text=report, parse_mode="HTML")
        print("✅ 下班统计报表已自动发送")
    except Exception as e: print(f"❌ 自动发送下班统计失败: {e}")

async def auto_reset_csv_job(context: ContextTypes.DEFAULT_TYPE):
    with csv_lock:
        init_csv_file()
        print("⏰ 新班次开始，CSV数据已安全重置。")


# ==================== 🧾 手动命令 ====================
async def manual_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(generate_report_text() + "\n💡 <i>提示：此报表由管理员手动调用生成。</i>", parse_mode="HTML")

async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        save_chat_id(update.message.chat_id)
        await update.message.reply_text(f"✅ 当前群 chat_id 已保存：\n<code>{update.message.chat_id}</code>", parse_mode="HTML")

async def test_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        save_chat_id(update.message.chat_id)
        await daily_report_job(context)


# ==================== 💬 消息处理 ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user: return

    user = update.effective_user
    chat_id = update.message.chat_id
    raw_text = update.message.text.strip()

    print("收到消息:", raw_text)

    for trad, simp in TRADITIONAL_MAP.items():
        if raw_text.startswith(trad):
            raw_text = simp + raw_text[len(trad):]
