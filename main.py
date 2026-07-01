import csv
import json
import os
import threading
from datetime import datetime, time, timedelta, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = os.getenv("TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
KNOWN_CHATS_FILE = os.path.join(DATA_DIR, "known_chats.json")
TZ_CHINA = timezone(timedelta(hours=8))

DEFAULT_ITEMS = {
    "上班": "🏁 开始工作", "下班": "🌙 结束工作下班", "回": "🔙 已返回工位",
    "wc小": "🚽 离开去洗手间(小)", "wc大": "💩 离开去洗手间(大)",
    "视频": "📹 离开去开视频/看视频", "开会": "🤝 进入会议/开会中",
    "吃饭": "🍱 离开去吃饭/就餐", "语音": "🎙️ 离开去发语音/听语音",
    "抽烟": "🚬 离开去抽烟", "AI": "🤖 申请AI室"
}

DEFAULT_CONFIG = {
    "start": "09:55", "end": "02:00", "report": "03:00", "reset": "05:05",
    "rooms": ["1号AI室", "2号AI室", "3号AI室", "4号AI室", "5号AI室"],
    "items": DEFAULT_ITEMS,
    "timeout_limits": {"wc小": 5, "wc大": 15, "吃饭": 30, "抽烟": 5},
    "count_limits": {},
    "group_count_limits": {"离岗": {"items": ["wc小", "wc大", "抽烟"], "limit": 5}},
    "report_mode": "auto", "enabled": True
}

TRAD_MAP = {"吃飯":"吃饭","語音":"语音","開會":"开会","抽煙":"抽烟","視頻":"视频","視频":"视频","號AI室":"号AI室","號ai室":"号AI室"}
csv_lock = threading.Lock()
json_lock = threading.Lock()

def load_json(path, default):
    with json_lock:
        if not os.path.exists(path): return default
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return default

def save_json(path, data):
    with json_lock:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def deep_default(): return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
def chat_id_str(update): return str(update.effective_chat.id)
def records_file(cid): return os.path.join(DATA_DIR, f"records_{cid}.csv")
def queue_file(cid): return os.path.join(DATA_DIR, f"queue_{cid}.json")

def ensure_csv(cid):
    p = records_file(cid)
    if not os.path.exists(p):
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["时间","日期","用户ID","昵称","动作项目","当前项目累计次数","考勤状态","离开时长"])

def get_cfg(cid):
    groups = load_json(GROUPS_FILE, {})
    if cid not in groups:
        groups[cid] = deep_default(); save_json(GROUPS_FILE, groups)
    cfg = groups[cid]
    changed = False
    d = deep_default()
    for k, v in d.items():
        if k not in cfg: cfg[k] = v; changed = True
    for k, v in DEFAULT_ITEMS.items():
        if k not in cfg["items"]: cfg["items"][k] = v; changed = True
    if changed: groups[cid] = cfg; save_json(GROUPS_FILE, groups)
    return cfg

def save_cfg(cid, cfg):
    groups = load_json(GROUPS_FILE, {}); groups[cid] = cfg; save_json(GROUPS_FILE, groups)

def remember_chat(cid):
    chats = load_json(KNOWN_CHATS_FILE, [])
    if cid not in chats: chats.append(cid); save_json(KNOWN_CHATS_FILE, chats)

def parse_hm(value):
    h, m = value.split(":"); return time(int(h), int(m), 0)

def business_date(dt): return (dt - timedelta(days=1)).strftime("%Y-%m-%d") if dt.time() < time(3,0,0) else dt.strftime("%Y-%m-%d")
def mention(uid, name): return f"<a href='tg://user?id={uid}'>{name or '用户'}</a>"

def normalize(raw, cfg):
    text = raw.strip()
    for a,b in TRAD_MAP.items(): text = text.replace(a,b)
    compact = text.replace(" ", "").replace("　", "")
    low = compact.lower()
    if low in ["ai","申请ai","我要ai","排ai"]: return "AI"
    if compact in ["AI室","ai室","房间","房間"]: return "AI室"
    if compact in ["排队","排隊","队列","隊列","AI排队","ai排队"]: return "排队"
    if compact in ["取消排队","取消排隊","退出排队","退出排隊","不排了"]: return "取消排队"
    if compact in ["报表","日报","出勤表","考勤表","统计"]: return "报表"
    if compact in ["配置","设置","群配置"]: return "配置"
    if compact in ["菜单","帮助"]: return "菜单"
    for room in cfg["rooms"]:
        if low in [room.lower(), room.replace("AI室","ai").lower()]: return room
    return text

def read_rows(cid):
    ensure_csv(cid)
    with open(records_file(cid), "r", encoding="utf-8-sig") as f: return list(csv.reader(f))

def append_row(cid, row):
    ensure_csv(cid)
    with csv_lock:
        with open(records_file(cid), "a", newline="", encoding="utf-8-sig") as f: csv.writer(f).writerow(row)

def today_count(cid, uid, action, bdate):
    return sum(1 for r in read_rows(cid)[1:] if len(r)>=5 and r[1]==bdate and str(r[2])==str(uid) and r[4]==action)

def group_count(cid, uid, actions, bdate):
    actions = set(actions)
    return sum(1 for r in read_rows(cid)[1:] if len(r)>=5 and r[1]==bdate and str(r[2])==str(uid) and r[4] in actions)

def load_queue(cid): return load_json(queue_file(cid), [])
def save_queue(cid, q): save_json(queue_file(cid), q)

def add_queue(cid, uid, name):
    q=load_queue(cid); uid=str(uid)
    for i,x in enumerate(q,1):
        if str(x.get("uid"))==uid: return False, i
    q.append({"uid":uid,"name":name,"time":datetime.now(TZ_CHINA).strftime("%Y-%m-%d %H:%M:%S")}); save_queue(cid,q); return True,len(q)

def remove_queue(cid, uid):
    q=load_queue(cid); uid=str(uid); nq=[x for x in q if str(x.get("uid"))!=uid]; save_queue(cid,nq); return len(nq)!=len(q)

def pop_queue(cid):
    q=load_queue(cid)
    if not q: return None
    x=q.pop(0); save_queue(cid,q); return x

def queue_text(cid):
    q=load_queue(cid)
    if not q: return "📋 <b>AI排队名单</b>\n\n✅ 当前无人排队。"
    return "📋 <b>AI排队名单</b>\n\n" + "\n".join(f"{i}. {mention(x['uid'], x['name'])}" for i,x in enumerate(q,1))

def active_rooms(cid, cfg):
    active={}
    for r in read_rows(cid)[1:]:
        if len(r)<5: continue
        uid,name,act=str(r[2]),r[3],r[4]
        if act in cfg["rooms"]:
            for room, info in list(active.items()):
                if info["uid"]==uid: active.pop(room, None)
            active[act]={"uid":uid,"name":name}
        elif act in ["回","下班"]:
            for room, info in list(active.items()):
                if info["uid"]==uid: active.pop(room, None)
    return active

def ai_status(cid,cfg):
    active=active_rooms(cid,cfg); lines=["🤖 <b>AI室状态</b>\n"]
    for room in cfg["rooms"]:
        lines.append(f"{room}：🚫 {mention(active[room]['uid'], active[room]['name'])} 使用中" if room in active else f"{room}：✅ 空闲")
    free=[r for r in cfg["rooms"] if r not in active]
    lines.append(f"\n✅ 可用：<b>{'、'.join(free) if free else '无'}</b>")
    lines.append(f"📋 当前排队人数：<b>{len(load_queue(cid))}</b>")
    return "\n".join(lines)

def last_leave(cid, uid, cfg):
    leave=set(cfg.get("timeout_limits",{}).keys()) | set(cfg.get("rooms",[])) | {"开会","视频","语音"}
    for r in reversed(read_rows(cid)):
        if len(r)<5 or str(r[2])!=str(uid): continue
        if r[4] in ["回","上班","下班"]: return None,None
        if r[4] in leave: return r[4],r[0]
    return None,None

def report_text(cid,cfg):
    now=datetime.now(TZ_CHINA); bdate=business_date(now); summary={}; last={}
    for r in read_rows(cid)[1:]:
        if len(r)<8 or r[1]!=bdate: continue
        uid,name,act,status,dur=r[2],r[3],r[4],r[6],r[7]
        tm=r[0].split(" ")[1][:5] if " " in r[0] else r[0][:5]
        summary.setdefault(uid,{"name":name,"上班":"❌ 未打卡","下班":"❌ 未打卡","actions":{}})
        if act=="上班": summary[uid]["上班"]=f"✅ {tm} ({status})"; last[uid]=None
        elif act=="下班": summary[uid]["下班"]=f"✅ {tm} ({status})"; last[uid]=None
        elif act!="回" and act!="AI":
            summary[uid]["actions"].setdefault(act,{"count":0,"mins":0}); summary[uid]["actions"][act]["count"]+=1; last[uid]=act
        elif act=="回":
            la=last.get(uid)
            if la and "分" in dur and la in summary[uid]["actions"]:
                try: summary[uid]["actions"][la]["mins"]+=int(dur.split("分")[0])
                except Exception: pass
            last[uid]=None
    if not summary: return f"📋 全员出勤总榜单 ({bdate})\n━━━━━━━━━━━━━━━━━━\n\nℹ️ 暂无任何打卡数据。"
    text=f"📋 全员出勤总榜单 ({bdate})\n━━━━━━━━━━━━━━━━━━\n\n"
    for uid,d in summary.items():
        text+=f"👤 人员：{d['name']}\n ├ ⏳ 上班状态： {d['上班']}\n ├ 🌙 下班状态： {d['下班']}\n"
        details=[]
        for act,info in d["actions"].items():
            icon=cfg["items"].get(act,"📊").split(" ")[0]
            details.append(f"{icon}{act} {info['count']}次" + (f" (累计 {info['mins']} 分钟)" if info["mins"] else ""))
        text+=f" └ 📝 出勤细节： {('、'.join(details) if details else '正常在岗，无离岗记录')}\n──────────────────\n"
    return text

async def send_report(bot,cid,chat_id,cfg,title="出勤报表"):
    text=report_text(cid,cfg)
    if len(text)<=3500:
        await bot.send_message(chat_id=chat_id,text=text,parse_mode="HTML")
    else:
        path=os.path.join(DATA_DIR,f"report_{cid}.txt")
        with open(path,"w",encoding="utf-8-sig") as f: f.write(text)
        with open(path,"rb") as f: await bot.send_document(chat_id=chat_id,document=f,filename=f"{title}_{datetime.now(TZ_CHINA).strftime('%Y-%m-%d_%H-%M-%S')}.txt",caption=f"📄 {title}内容较长，已自动生成TXT文件。")

def config_text(cid,cfg):
    gl=[]
    for name,data in cfg.get("group_count_limits",{}).items(): gl.append(f"{name}：{' + '.join(data['items'])} 合计 {data['limit']} 次")
    return f"⚙️ <b>本群配置</b>\n\n上班：{cfg['start']}\n下班：{cfg['end']}\n日报：{cfg['report']}\n清空：{cfg['reset']}\nAI室：{'、'.join(cfg['rooms'])}\n\n项目：{'、'.join(cfg['items'].keys())}\n\n超时限制：{cfg.get('timeout_limits',{})}\n单项次数限制：{cfg.get('count_limits',{})}\n合计次数限制：{('；'.join(gl) if gl else '无')}"

def menu_text(): return "📋 <b>企业版 V5 菜单</b>\n\n普通文字：AI / AI室 / 排队 / 取消排队 / 报表 / 配置\n\n时间：/setstart 09:55 /setend 02:00 /setreport 03:00 /setreset 05:05\nAI室：/setrooms 5 /addroom 6号AI室 /delroom 5号AI室\n项目：/additem 培训 📚 进入培训 /delitem 培训\n限制：/settimeout 吃饭 30 /limit wc大 3 /limitgroup 离岗 5 wc小 wc大 抽烟"

async def timeout_alert(context):
    d=context.job.data
    await context.bot.send_message(chat_id=d["chat_id"],text=f"🚨 <b>超时警告</b>\n\n👤 {mention(d['uid'],d['name'])}\n项目：<b>{d['action']}</b>\n已超过 <b>{d['minutes']}</b> 分钟！",parse_mode="HTML")

async def scheduler(context):
    now=datetime.now(TZ_CHINA).strftime("%H:%M")
    for cid in load_json(KNOWN_CHATS_FILE,[]):
        cfg=get_cfg(cid)
        if not cfg.get("enabled",True): continue
        if cfg.get("report")==now:
            try: await send_report(context.bot,cid,int(cid),cfg,"自动出勤日报"); print("已发送日报",cid,flush=True)
            except Exception as e: print("日报失败",cid,e,flush=True)
        if cfg.get("reset")==now:
            try:
                if os.path.exists(records_file(cid)): os.remove(records_file(cid))
                ensure_csv(cid); save_queue(cid,[]); print("已清空",cid,flush=True)
            except Exception as e: print("清空失败",cid,e,flush=True)

async def cmd_chatid(update, context):
    cid=chat_id_str(update); remember_chat(cid); get_cfg(cid)
    await update.message.reply_text(f"✅ 当前群已保存：<code>{cid}</code>",parse_mode="HTML")
async def cmd_config(update, context): await update.message.reply_text(config_text(chat_id_str(update),get_cfg(chat_id_str(update))),parse_mode="HTML")
async def cmd_menu(update, context): await update.message.reply_text(menu_text(),parse_mode="HTML")
async def cmd_report(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid); remember_chat(cid); await send_report(context.bot,cid,update.effective_chat.id,cfg,"手动出勤报表")
async def set_time_cmd(update, context, key, label):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if not context.args: return await update.message.reply_text(f"用法：/{label} 09:55")
    try: parse_hm(context.args[0])
    except Exception: return await update.message.reply_text("❌ 时间格式错误，请用 HH:MM，例如 09:55")
    cfg[key]=context.args[0]; save_cfg(cid,cfg); remember_chat(cid); await update.message.reply_text(f"✅ 已设置 {key} = {context.args[0]}")
async def cmd_setrooms(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if not context.args: return await update.message.reply_text("用法：/setrooms 5")
    n=int(context.args[0]); cfg["rooms"]=[f"{i}号AI室" for i in range(1,n+1)]
    for room in cfg["rooms"]: cfg["items"][room]=f"🤖 进入 {room} 使用人工智能"
    save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置AI室：{'、'.join(cfg['rooms'])}")
async def cmd_addroom(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if not context.args: return await update.message.reply_text("用法：/addroom 6号AI室")
    room=" ".join(context.args).strip()
    if room not in cfg["rooms"]: cfg["rooms"].append(room)
    cfg["items"][room]=f"🤖 进入 {room} 使用人工智能"; save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已新增AI室：{room}")
async def cmd_delroom(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if not context.args: return await update.message.reply_text("用法：/delroom 5号AI室")
    room=" ".join(context.args).strip(); cfg["rooms"]=[r for r in cfg["rooms"] if r!=room]; cfg["items"].pop(room,None); save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已删除AI室：{room}")
async def cmd_additem(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if not context.args: return await update.message.reply_text("用法：/additem 培训 📚 进入培训")
    name=context.args[0]; desc=" ".join(context.args[1:]).strip() or f"📌 {name}"; cfg["items"][name]=desc; save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已新增项目：{name}")
async def cmd_delitem(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if not context.args: return await update.message.reply_text("用法：/delitem 培训")
    name=context.args[0]
    if name in ["上班","下班","回"]: return await update.message.reply_text("❌ 上班/下班/回 是核心项目，不能删除。")
    cfg["items"].pop(name,None); save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已删除项目：{name}")
async def cmd_settimeout(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if len(context.args)<2: return await update.message.reply_text("用法：/settimeout 吃饭 30")
    cfg.setdefault("timeout_limits",{})[context.args[0]]=int(context.args[1]); save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置 {context.args[0]} 超时提醒：{context.args[1]} 分钟")
async def cmd_limit(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if len(context.args)<2: return await update.message.reply_text("用法：/limit wc大 3")
    cfg.setdefault("count_limits",{})[context.args[0]]=int(context.args[1]); save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置 {context.args[0]} 每日超过 {context.args[1]} 次警告")
async def cmd_limitgroup(update, context):
    cid=chat_id_str(update); cfg=get_cfg(cid)
    if len(context.args)<3: return await update.message.reply_text("用法：/limitgroup 离岗 5 wc小 wc大 抽烟")
    cfg.setdefault("group_count_limits",{})[context.args[0]]={"limit":int(context.args[1]),"items":context.args[2:]}; save_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置合计限制：{context.args[0]} = {' + '.join(context.args[2:])} 合计 {context.args[1]} 次")

async def handle_message(update, context):
    if not update.message or not update.message.text or not update.effective_user: return
    cid=chat_id_str(update); cfg=get_cfg(cid); remember_chat(cid); user=update.effective_user
    raw=update.message.text.strip(); text=normalize(raw,cfg); print("收到消息:",cid,raw,flush=True)
    if text=="菜单": return await update.message.reply_text(menu_text(),parse_mode="HTML")
    if text=="配置": return await update.message.reply_text(config_text(cid,cfg),parse_mode="HTML")
    if text=="报表": return await send_report(context.bot,cid,update.effective_chat.id,cfg,"出勤报表")
    if text=="AI室": return await update.message.reply_text(ai_status(cid,cfg),parse_mode="HTML")
    if text=="排队": return await update.message.reply_text(queue_text(cid),parse_mode="HTML")
    if text=="取消排队": return await update.message.reply_text("✅ 已退出AI排队队列。" if remove_queue(cid,user.id) else "ℹ️ 你当前不在AI排队队列中。")
    if text=="AI":
        active=active_rooms(cid,cfg); free=[r for r in cfg["rooms"] if r not in active]
        if free: return await update.message.reply_text(f"🤖 <b>AI室申请</b>\n\n{ai_status(cid,cfg)}\n\n请发送：<b>{free[0]}</b>",parse_mode="HTML")
        added,pos=add_queue(cid,user.id,user.full_name)
        return await update.message.reply_text((f"✅ 已加入AI排队，第 <b>{pos}</b> 位。" if added else f"ℹ️ 你已在AI排队，第 <b>{pos}</b> 位。"),parse_mode="HTML")
    items=dict(cfg["items"])
    for room in cfg["rooms"]: items.setdefault(room,f"🤖 进入 {room} 使用人工智能")
    action=None
    for key in items:
        if text.lower().startswith(key.lower()): action=key; break
    if not action: return
    if action in cfg["rooms"]:
        active=active_rooms(cid,cfg)
        if action in active and active[action]["uid"]!=str(user.id):
            free=[r for r in cfg["rooms"] if r not in active]
            if free: return await update.message.reply_text(f"⚠️ {action} 已被 {active[action]['name']} 使用中。\n✅ 请去：{'、'.join(free)}")
            added,pos=add_queue(cid,user.id,user.full_name)
            return await update.message.reply_text(f"❌ AI室已全部占用。\n✅ 已加入排队，第 {pos} 位。")
        remove_queue(cid,user.id)
    released=None
    if action in ["回","下班"]:
        for room,info in active_rooms(cid,cfg).items():
            if info["uid"]==str(user.id): released=room; break
    now=datetime.now(TZ_CHINA); bdate=business_date(now); status="正常"
    if action=="上班" and (now.time()>parse_hm(cfg["start"]) or now.time()<parse_hm(cfg["end"])): status="⚠️ 迟到"
    if action=="下班" and now.time()<parse_hm(cfg["end"]) and now.time()>time(3,0,0): status="⚠️ 早退"
    for job in context.job_queue.get_jobs_by_name(f"timeout_{cid}_{user.id}"): job.schedule_removal()
    duration="N/A"; duration_msg=""
    if action=="回":
        la,lt=last_leave(cid,user.id,cfg)
        if lt:
            diff=now-datetime.strptime(lt,"%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_CHINA); sec=int(diff.total_seconds())
            duration=f"{sec//60}分{sec%60}秒"; duration_msg=f"⏱️ 本次 [{la}] 共计离开：<b>{sec//60}</b> 分 <b>{sec%60}</b> 秒\n"
        else: duration_msg="ℹ️ 未找到离开记录。\n"
    past=today_count(cid,user.id,action,bdate)+1
    append_row(cid,[now.strftime("%Y-%m-%d %H:%M:%S"),bdate,user.id,user.full_name,action,past,status,duration])
    if action in cfg.get("timeout_limits",{}):
        mins=int(cfg["timeout_limits"][action]); context.job_queue.run_once(timeout_alert,when=timedelta(minutes=mins),name=f"timeout_{cid}_{user.id}",data={"chat_id":update.effective_chat.id,"uid":user.id,"name":user.full_name,"action":action,"minutes":mins})
    reply=f"<b>{items.get(action,action)} 登记成功！</b>\n⏰ 时间：{now.strftime('%H:%M:%S')}\n🔢 今日该项累计：<b>{past}</b> 次\n"
    if duration_msg: reply+=duration_msg
    if action in cfg.get("count_limits",{}) and past>int(cfg["count_limits"][action]): reply+=f"🚨 <b>次数警告：</b>{action} 今日第 <b>{past}</b> 次，超过规定 <b>{cfg['count_limits'][action]}</b> 次！\n"
    for lname,data in cfg.get("group_count_limits",{}).items():
        if action in data.get("items",[]):
            total=group_count(cid,user.id,data["items"],bdate)+1
            reply+=f"📈 {lname}合计：<b>{total}/{data['limit']}</b> 次\n"
            if total>int(data["limit"]): reply+=f"⚠️ <b>{lname}次数已超出每日上限！</b>\n"
    if status!="正常": reply+=f"📢 考勤提醒：{status}\n"
    await update.message.reply_text(reply,parse_mode="HTML")
    if released:
        nxt=pop_queue(cid)
        if nxt: await context.bot.send_message(chat_id=update.effective_chat.id,text=f"📢 <b>AI室排队叫号</b>\n\n<b>{released}</b> 已空出。\n请 {mention(nxt['uid'],nxt['name'])} 去 <b>{released}</b>。\n请发送：<b>{released}</b> 正式登记。",parse_mode="HTML")

def main():
    if not TOKEN: print("❌ 没有读取到 TOKEN 环境变量"); return
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("chatid",cmd_chatid)); app.add_handler(CommandHandler("config",cmd_config)); app.add_handler(CommandHandler("menu",cmd_menu)); app.add_handler(CommandHandler("report",cmd_report)); app.add_handler(CommandHandler("testreport",cmd_report))
    app.add_handler(CommandHandler("setstart",lambda u,c:set_time_cmd(u,c,"start","setstart"))); app.add_handler(CommandHandler("setend",lambda u,c:set_time_cmd(u,c,"end","setend"))); app.add_handler(CommandHandler("setreport",lambda u,c:set_time_cmd(u,c,"report","setreport"))); app.add_handler(CommandHandler("setreset",lambda u,c:set_time_cmd(u,c,"reset","setreset")))
    app.add_handler(CommandHandler("setrooms",cmd_setrooms)); app.add_handler(CommandHandler("addroom",cmd_addroom)); app.add_handler(CommandHandler("delroom",cmd_delroom)); app.add_handler(CommandHandler("additem",cmd_additem)); app.add_handler(CommandHandler("delitem",cmd_delitem)); app.add_handler(CommandHandler("settimeout",cmd_settimeout)); app.add_handler(CommandHandler("limit",cmd_limit)); app.add_handler(CommandHandler("limitgroup",cmd_limitgroup))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    if app.job_queue is None: print('❌ JobQueue 未启用'); return
    app.job_queue.run_repeating(scheduler, interval=60, first=10, name="v5_scheduler")
    print("✅ 企业版 V5 已启动：无代码配置 / 多群独立 / AI排队 / 合计限制 / TXT日报", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__ == "__main__": main()
