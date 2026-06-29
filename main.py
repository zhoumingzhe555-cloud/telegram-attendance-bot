
import csv, os, json, threading
from datetime import datetime, time, timedelta, timezone
from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import Update

TOKEN = os.getenv("TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
CHAT_FILE = os.path.join(DATA_DIR, "known_chats.json")
TZ_CHINA = timezone(timedelta(hours=8))

DEFAULT_CONFIG = {
    "start": "09:55", "end": "02:00", "report": "03:00", "reset": "05:05",
    "rooms": ["1号AI室", "2号AI室", "3号AI室"],
    "timeout_limits": {"wc小": 5, "wc大": 15, "吃饭": 30, "抽烟": 5},
    "count_limits": {"wc大": 3},
    "items": {"上班":"🏁 开始工作","下班":"🌙 结束工作下班","回":"🔙 已返回工位","wc小":"🚽 离开去洗手间(小)","wc大":"💩 离开去洗手间(大)","视频":"📹 离开去开视频/看视频","开会":"🤝 进入会议/开会中","吃饭":"🍱 离开去吃饭/就餐","语音":"🎙️ 离开去发语音/听语音","抽烟":"🚬 离开去抽烟","AI":"🤖 申请AI室"}
}
TRAD_MAP = {"吃飯":"吃饭","語音":"语音","開會":"开会","抽煙":"抽烟","視頻":"视频","視频":"视频","號AI室":"号AI室","號ai室":"号AI室"}
lock = threading.Lock()

def jload(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def jsave(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def get_cid(update): return str(update.message.chat_id)

def copy_default():
    return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))

def group_cfg(cid):
    groups = jload(GROUPS_FILE, {})
    if cid not in groups:
        groups[cid] = copy_default(); jsave(GROUPS_FILE, groups)
    cfg = groups[cid]
    for k,v in DEFAULT_CONFIG.items(): cfg.setdefault(k, json.loads(json.dumps(v, ensure_ascii=False)))
    return cfg

def save_group_cfg(cid, cfg):
    groups = jload(GROUPS_FILE, {}); groups[cid] = cfg; jsave(GROUPS_FILE, groups)

def csv_file(cid): return os.path.join(DATA_DIR, f"records_{cid}.csv")
def queue_file(cid): return os.path.join(DATA_DIR, f"queue_{cid}.json")

def ensure_csv(cid):
    p = csv_file(cid)
    if not os.path.exists(p):
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["时间","日期","用户ID","昵称","动作项目","当前项目累计次数","考勤状态","离开时长"])

def parse_hm(s):
    h,m=s.split(":"); return time(int(h), int(m), 0)

def business_date(dt): return (dt-timedelta(days=1)).strftime("%Y-%m-%d") if dt.time()<time(3,0) else dt.strftime("%Y-%m-%d")

def normalize(txt, cfg):
    t=txt.strip()
    for a,b in TRAD_MAP.items(): t=t.replace(a,b)
    c=t.replace(" ","").replace("　",""); l=c.lower()
    if l in ["ai","申请ai","排ai","我要ai"]: return "AI"
    if c in ["AI室","ai室","房间","房間"]: return "AI室"
    if c in ["排队","排隊","队列","隊列","AI排队","ai排队"]: return "排队"
    if c in ["取消排队","取消排隊","退出排队","退出排隊","不排了"]: return "取消排队"
    if c in ["报表","日报","出勤表","考勤表","统计"]: return "报表"
    if c in ["配置","设置","群配置"]: return "配置"
    if c.lower() in ["chatid","群id","保存群id"]: return "chatid"
    for r in cfg.get("rooms",[]):
        if c.lower() in [r.lower(), r.replace("AI室","ai").lower(), r.replace("AI室","").lower()+"号ai"]: return r
    return t

def mention(uid,name): return f"<a href='tg://user?id={uid}'>{name or '用户'}</a>"

def known_add(cid):
    chats=jload(CHAT_FILE,[])
    if cid not in chats: chats.append(cid); jsave(CHAT_FILE,chats)

def read_rows(cid):
    ensure_csv(cid)
    with open(csv_file(cid),"r",encoding="utf-8-sig") as f: return list(csv.reader(f))

def append_row(cid,row):
    ensure_csv(cid)
    with open(csv_file(cid),"a",newline="",encoding="utf-8-sig") as f: csv.writer(f).writerow(row)

def load_queue(cid): return jload(queue_file(cid), [])
def save_queue(cid,q): jsave(queue_file(cid), q)

def add_queue(cid, uid, name):
    q=load_queue(cid); uid=str(uid)
    for i,x in enumerate(q,1):
        if x.get("uid")==uid: return False,i
    q.append({"uid":uid,"name":name,"time":datetime.now(TZ_CHINA).strftime("%F %T")}); save_queue(cid,q); return True,len(q)

def remove_queue(cid, uid):
    q=load_queue(cid); uid=str(uid); nq=[x for x in q if x.get("uid")!=uid]
    save_queue(cid,nq); return len(q)!=len(nq)

def pop_queue(cid):
    q=load_queue(cid)
    if not q: return None
    x=q.pop(0); save_queue(cid,q); return x

def today_count(cid,uid,action,bdate):
    return sum(1 for r in read_rows(cid)[1:] if len(r)>=5 and r[1]==bdate and str(r[2])==str(uid) and r[4]==action)

def active_rooms(cid,cfg):
    active={}
    for r in read_rows(cid)[1:]:
        if len(r)<5: continue
        uid,name,act=str(r[2]),r[3],r[4]
        if act in cfg.get("rooms",[]):
            for rm,info in list(active.items()):
                if info["uid"]==uid: active.pop(rm,None)
            active[act]={"uid":uid,"name":name}
        elif act in ["回","下班"]:
            for rm,info in list(active.items()):
                if info["uid"]==uid: active.pop(rm,None)
    return active

def last_leave(cid,uid,cfg):
    leave=set(cfg.get("timeout_limits",{}).keys()) | {"开会","视频","语音"} | set(cfg.get("rooms",[]))
    for r in reversed(read_rows(cid)):
        if len(r)<5 or str(r[2])!=str(uid): continue
        if r[4] in ["回","上班","下班"]: return None,None
        if r[4] in leave: return r[4],r[0]
    return None,None

def ai_status(cid,cfg):
    active=active_rooms(cid,cfg); lines=["🤖 <b>AI室状态</b>\n"]
    for room in cfg.get("rooms",[]):
        lines.append(f"{room}：🚫 {mention(active[room]['uid'],active[room]['name'])} 使用中" if room in active else f"{room}：✅ 空闲")
    free=[r for r in cfg.get("rooms",[]) if r not in active]
    lines.append(f"\n✅ 可用：<b>{'、'.join(free) if free else '无'}</b>")
    lines.append(f"📋 当前排队人数：<b>{len(load_queue(cid))}</b>")
    return "\n".join(lines)

def queue_text(cid):
    q=load_queue(cid)
    if not q: return "📋 <b>AI排队名单</b>\n\n✅ 当前无人排队。"
    return "📋 <b>AI排队名单</b>\n\n" + "\n".join(f"{i}. {mention(x['uid'],x['name'])}" for i,x in enumerate(q,1))

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
                except: pass
            last[uid]=None
    if not summary: return f"📋 全员出勤总榜单 ({bdate})\n━━━━━━━━━━━━━━━━━━\n\nℹ️ 暂无任何打卡数据。"
    text=f"📋 全员出勤总榜单 ({bdate})\n━━━━━━━━━━━━━━━━━━\n\n"
    for uid,d in summary.items():
        text+=f"👤 人员：{d['name']}\n ├ ⏳ 上班状态： {d['上班']}\n ├ 🌙 下班状态： {d['下班']}\n"
        details=[]
        for a,info in d["actions"].items():
            icon=cfg.get("items",{}).get(a,"📊").split(" ")[0]
            details.append(f"{icon}{a} {info['count']}次" + (f" (累计 {info['mins']} 分钟)" if info['mins'] else ""))
        text+=f" └ 📝 出勤细节： {('、'.join(details) if details else '正常在岗，无离岗记录')}\n──────────────────\n"
    return text

async def send_report(bot,cid,chat_id,cfg,title="出勤报表"):
    text=report_text(cid,cfg)
    if len(text)<=3500: await bot.send_message(chat_id=chat_id,text=text,parse_mode="HTML")
    else:
        p=os.path.join(DATA_DIR,f"report_{cid}.txt")
        with open(p,"w",encoding="utf-8-sig") as f: f.write(text)
        with open(p,"rb") as f: await bot.send_document(chat_id=chat_id,document=f,filename=f"{title}_{datetime.now(TZ_CHINA).strftime('%F_%H-%M-%S')}.txt",caption=f"📄 {title}内容较长，已自动生成TXT文件。")

async def timeout_alert(context):
    d=context.job.data
    await context.bot.send_message(chat_id=d["chat_id"],text=f"🚨 <b>超时警告</b>\n\n👤 {mention(d['uid'],d['name'])}\n项目：<b>{d['action']}</b>\n已超过 <b>{d['mins']}</b> 分钟！",parse_mode="HTML")

async def daily_job(context):
    now=datetime.now(TZ_CHINA).strftime("%H:%M")
    for cid in jload(CHAT_FILE,[]):
        cfg=group_cfg(cid)
        if cfg.get("report")==now:
            try: await send_report(context.bot,cid,int(cid),cfg,"自动出勤日报")
            except Exception as e: print("日报失败",cid,e)
        if cfg.get("reset")==now:
            p=csv_file(cid)
            if os.path.exists(p): os.remove(p)
            ensure_csv(cid); save_queue(cid,[]); print("已清空",cid)

async def report_cmd(update,context):
    cid=get_cid(update); cfg=group_cfg(cid); known_add(cid); await send_report(context.bot,cid,update.message.chat_id,cfg,"手动出勤报表")
async def chatid_cmd(update,context):
    cid=get_cid(update); known_add(cid); group_cfg(cid); await update.message.reply_text(f"✅ 当前群已保存：<code>{cid}</code>",parse_mode="HTML")
async def config_cmd(update,context):
    cid=get_cid(update); cfg=group_cfg(cid)
    await update.message.reply_text(f"⚙️ <b>本群配置</b>\n上班：{cfg['start']}\n下班：{cfg['end']}\n日报：{cfg['report']}\n清空：{cfg['reset']}\nAI室：{'、'.join(cfg['rooms'])}\n次数限制：{cfg.get('count_limits',{})}\n\n/setstart 09:55\n/setend 02:00\n/setreport 03:00\n/setreset 05:05\n/setrooms 3\n/limit wc大 3",parse_mode="HTML")
async def set_cmd(update,context,key):
    cid=get_cid(update); cfg=group_cfg(cid)
    if not context.args: return await config_cmd(update,context)
    cfg[key]=context.args[0]; save_group_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置 {key} = {context.args[0]}")
async def setrooms_cmd(update,context):
    cid=get_cid(update); cfg=group_cfg(cid)
    if not context.args: return await update.message.reply_text("用法：/setrooms 3")
    n=int(context.args[0]); cfg["rooms"]=[f"{i}号AI室" for i in range(1,n+1)]
    for r in cfg["rooms"]: cfg["items"][r]=f"🤖 进入 {r} 使用人工智能"
    save_group_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置AI室：{'、'.join(cfg['rooms'])}")
async def limit_cmd(update,context):
    cid=get_cid(update); cfg=group_cfg(cid)
    if len(context.args)<2: return await update.message.reply_text("用法：/limit wc大 3")
    cfg.setdefault("count_limits",{})[context.args[0]]=int(context.args[1]); save_group_cfg(cid,cfg); await update.message.reply_text(f"✅ 已设置 {context.args[0]} 每日超过 {context.args[1]} 次警告")

async def msg(update:Update, context):
    if not update.message or not update.message.text or not update.effective_user: return
    cid=get_cid(update); cfg=group_cfg(cid); known_add(cid); user=update.effective_user; text=normalize(update.message.text,cfg)
    if text=="chatid": return await chatid_cmd(update,context)
    if text=="配置": return await config_cmd(update,context)
    if text=="报表": return await send_report(context.bot,cid,update.message.chat_id,cfg,"出勤报表")
    if text=="AI室": return await update.message.reply_text(ai_status(cid,cfg),parse_mode="HTML")
    if text=="排队": return await update.message.reply_text(queue_text(cid),parse_mode="HTML")
    if text=="取消排队": return await update.message.reply_text("✅ 已退出AI排队队列。" if remove_queue(cid,user.id) else "ℹ️ 你当前不在AI排队队列中。")
    if text=="AI":
        active=active_rooms(cid,cfg); free=[r for r in cfg["rooms"] if r not in active]
        if free: return await update.message.reply_text(f"🤖 <b>AI室申请</b>\n\n{ai_status(cid,cfg)}\n\n请发送：<b>{free[0]}</b>",parse_mode="HTML")
        added,pos=add_queue(cid,user.id,user.full_name); return await update.message.reply_text((f"✅ 已加入AI排队，第 <b>{pos}</b> 位。" if added else f"ℹ️ 你已在AI排队，第 <b>{pos}</b> 位。"),parse_mode="HTML")
    items={**cfg["items"]}
    for r in cfg["rooms"]: items.setdefault(r,f"🤖 进入 {r} 使用人工智能")
    action=next((k for k in items if text.lower().startswith(k.lower())), None)
    if not action: return
    if action in cfg["rooms"]:
        active=active_rooms(cid,cfg)
        if action in active and active[action]["uid"]!=str(user.id):
            free=[r for r in cfg["rooms"] if r not in active]
            if free: return await update.message.reply_text(f"⚠️ {action} 已被 {active[action]['name']} 使用中。\n✅ 请去：{'、'.join(free)}")
            added,pos=add_queue(cid,user.id,user.full_name); return await update.message.reply_text(f"❌ AI室都已占用。\n✅ 已加入排队，第 {pos} 位。")
        remove_queue(cid,user.id)
    released=None
    if action in ["回","下班"]:
        for room,info in active_rooms(cid,cfg).items():
            if info["uid"]==str(user.id): released=room; break
    now=datetime.now(TZ_CHINA); bdate=business_date(now); status="正常"
    if action=="上班" and (now.time()>parse_hm(cfg["start"]) or now.time()<parse_hm(cfg["end"])): status="⚠️ 迟到"
    if action=="下班" and now.time()<parse_hm(cfg["end"]) and now.time()>time(3,0): status="⚠️ 早退"
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
        mins=cfg["timeout_limits"][action]
        context.job_queue.run_once(timeout_alert,when=timedelta(minutes=mins),name=f"timeout_{cid}_{user.id}",data={"chat_id":update.message.chat_id,"uid":user.id,"name":user.full_name,"action":action,"mins":mins})
    reply=f"<b>{items.get(action,action)} 登记成功！</b>\n⏰ 时间：{now.strftime('%H:%M:%S')}\n🔢 今日累计：<b>{past}</b> 次\n"
    reply+=duration_msg
    if action in cfg.get("count_limits",{}) and past>cfg["count_limits"][action]: reply+=f"🚨 <b>次数警告：</b>{action} 今日第 <b>{past}</b> 次，超过规定 <b>{cfg['count_limits'][action]}</b> 次！\n"
    if status!="正常": reply+=f"📢 考勤提醒：{status}\n"
    await update.message.reply_text(reply,parse_mode="HTML")
    if released:
        nxt=pop_queue(cid)
        if nxt: await context.bot.send_message(chat_id=update.message.chat_id,text=f"📢 <b>AI室排队叫号</b>\n\n<b>{released}</b> 已空出。\n请 {mention(nxt['uid'],nxt['name'])} 去 <b>{released}</b>。\n请发送：<b>{released}</b> 正式登记。",parse_mode="HTML")

def main():
    if not TOKEN: print("❌ 没有读取到 TOKEN 环境变量"); return
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("report",report_cmd)); app.add_handler(CommandHandler("testreport",report_cmd)); app.add_handler(CommandHandler("chatid",chatid_cmd)); app.add_handler(CommandHandler("config",config_cmd))
    app.add_handler(CommandHandler("setstart",lambda u,c:set_cmd(u,c,"start"))); app.add_handler(CommandHandler("setend",lambda u,c:set_cmd(u,c,"end"))); app.add_handler(CommandHandler("setreport",lambda u,c:set_cmd(u,c,"report"))); app.add_handler(CommandHandler("setreset",lambda u,c:set_cmd(u,c,"reset")))
    app.add_handler(CommandHandler("setrooms",setrooms_cmd)); app.add_handler(CommandHandler("limit",limit_cmd)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg))
    app.job_queue.run_repeating(daily_job, interval=60, first=10, name="multi_group_scheduler")
    print("✅ 企业版 V4 已启动：多群独立配置 / AI排队 / TXT日报 / 次数警告")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__=="__main__": main()
