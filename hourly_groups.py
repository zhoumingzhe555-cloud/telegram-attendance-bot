"""Per-chat rosters and short-lived hourly leave events. Standard library only."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO

TZ = timezone(timedelta(hours=8))
ACTIONS = {'wc小', 'wc大', '抽烟'}
ROSTER = {
    '渣男组': '奇奇 来财 汪宇 阿哲 山河 凯轩 浮尘 梓奇 土豆 小壮 阿尧 小杨'.split(),
    '金花组': '金圣 吉祥 雷武 李枫 陈思诚 宏图 锦鲤 凯凯 AK 旺仔 无情 红牛'.split(),
    '杨逍组': '大海 胖子 阿军 伊泽 东森 阿发 华子 阿飞 佳好 李强 金宝 东子'.split(),
    '徐江组': '星龙 白鲨 李阳 画皮 阿林 阿吉 如意 大威 小瑶 娜娜 孟川'.split(),
}


def hour(dt):
    return int(dt.replace(minute=0, second=0, microsecond=0).timestamp())


class HourlyGroups:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS chats(cid TEXT PRIMARY KEY, sent INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS members(
                    cid TEXT, team TEXT, name TEXT, uid TEXT,
                    PRIMARY KEY(cid, name), UNIQUE(cid, uid));
                CREATE TABLE IF NOT EXISTS attendance_sent(cid TEXT PRIMARY KEY, day TEXT);
                CREATE TABLE IF NOT EXISTS punches(
                    cid TEXT, mid INTEGER, at INTEGER, uid TEXT, name TEXT,
                    PRIMARY KEY(cid, mid));
                CREATE TABLE IF NOT EXISTS events(
                    cid TEXT, mid INTEGER, at INTEGER, uid TEXT, name TEXT, team TEXT,
                    PRIMARY KEY(cid, mid));
                CREATE INDEX IF NOT EXISTS events_time ON events(cid, at);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self, cid, now):
        with self.connect() as db:
            if db.execute('SELECT 1 FROM chats WHERE cid=?', (cid,)).fetchone():
                return False
            db.execute('INSERT INTO chats VALUES (?,?)', (cid, hour(now)))
            db.executemany('INSERT INTO members VALUES (?,?,?,NULL)',
                           [(cid, team, name) for team, names in ROSTER.items() for name in names])
        return True

    def members(self, cid):
        with self.connect() as db:
            return db.execute('SELECT team,name,uid FROM members WHERE cid=? ORDER BY rowid', (cid,)).fetchall()

    def set_member(self, cid, team, name, uid=None):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM chats WHERE cid=?', (cid,)).fetchone():
                raise ValueError('请先发送 /initgroups 导入名单。')
            prior = db.execute('SELECT uid FROM members WHERE cid=? AND name=?', (cid, name)).fetchone()
            if uid is not None and prior and prior[0] and prior[0] != uid:
                raise ValueError('该姓名已绑定另一位成员，请使用不同的名单姓名。')
            if uid is not None:
                db.execute('DELETE FROM members WHERE cid=? AND uid=? AND name<>?', (cid, uid, name))
            bound = uid if uid is not None else (prior[0] if prior else None)
            db.execute('INSERT OR REPLACE INTO members VALUES (?,?,?,?)', (cid, team, name, bound))

    def remove(self, cid, name=None, uid=None):
        with self.connect() as db:
            if uid is not None:
                return db.execute('DELETE FROM members WHERE cid=? AND uid=?', (cid, uid)).rowcount
            return db.execute('DELETE FROM members WHERE cid=? AND name=?', (cid, name)).rowcount

    def record(self, cid, mid, at, uid, name, action):
        if action not in ACTIONS | {'上班'}:
            return
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM chats WHERE cid=?', (cid,)).fetchone():
                return
            if action == '上班':
                db.execute('INSERT OR IGNORE INTO punches VALUES (?,?,?,?,?)', (cid, mid, int(at.timestamp()), uid, name))
                db.execute('DELETE FROM punches WHERE at<?', (int(at.timestamp()) - 86400,))
                return
            bound = db.execute('SELECT team,name FROM members WHERE cid=? AND uid=?', (cid, uid)).fetchone()
            team, label = bound if bound else (None, name)
            db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)',
                       (cid, mid, int(at.timestamp()), uid, label, team))
            # Retain at most 24 hours even when sending fails for a long period.
            db.execute('DELETE FROM events WHERE at<?', (int(at.timestamp()) - 86400,))

    def report(self, cid, start, end):
        members = self.members(cid)
        groups = {}
        lookup = {}
        for team, name, uid in members:
            groups.setdefault(team, {})[name] = 0
            if uid:
                lookup[uid] = (team, name)
        with self.connect() as db:
            events = db.execute('SELECT uid,name,team FROM events WHERE cid=? AND at>=? AND at<? ORDER BY at', (cid, start, end)).fetchall()
        unknown = {}
        for uid, name, team in events:
            if team is None and uid in lookup:
                team, name = lookup[uid]
            if team is None:
                label = f'{name}(ID:{uid})'
                unknown[label] = unknown.get(label, 0) + 1
            else:
                counts = groups.setdefault(team, {})
                counts[name] = counts.get(name, 0) + 1
        a, b = datetime.fromtimestamp(start, TZ), datetime.fromtimestamp(end, TZ)
        lines = ['【每小时离岗统计】', f'{a:%m-%d %H:%M}—{b:%m-%d %H:%M}', 'wc小＋wc大＋抽烟', '']
        for team, counts in groups.items():
            lines.append(f"{team}：" + '、'.join(f'{name}{count}' for name, count in counts.items()) + f'，合计{sum(counts.values())}次')
        if unknown:
            lines.extend(['', '未分组：' + '、'.join(f'{name} {count}次' for name, count in unknown.items()) + f'，合计{sum(unknown.values())}次'])
        pending = sum(uid is None for _, _, uid in members)
        lines.extend(['', f'全群合计：{len(events)}次'])
        if pending:
            lines.append(f'名单中还有{pending}人待绑定；管理员回复成员消息发送 /setgroup 组名 名单姓名。')
        return '\n'.join(lines)

    async def send(self, bot, cid, text):
        if len(text.encode('utf-16-le')) // 2 <= 3500:
            await bot.send_message(chat_id=int(cid), text=text, parse_mode=None)
        else:
            with BytesIO(text.encode('utf-8-sig')) as document:
                await bot.send_document(chat_id=int(cid), document=document, filename='每小时离岗统计.txt')

    def attendance_report(self, cid, start, now):
        members = self.members(cid)
        with self.connect() as db:
            present = {r[0] for r in db.execute(
                'SELECT DISTINCT uid FROM punches WHERE cid=? AND at>=? AND at<=?',
                (cid, int(start.timestamp()), int(now.timestamp())))}
        groups = {}
        bound = set()
        for team, name, uid in members:
            stat = groups.setdefault(team, [0, 0, 0])
            stat[1] += 1
            if uid is None:
                stat[2] += 1
            else:
                bound.add(uid)
                stat[0] += uid in present
        lines = ['【各组上班打卡人数】', f'截至 {now:%m-%d %H:%M}', '']
        for team, (count, total, pending) in groups.items():
            lines.append(f'{team}：已打卡{count}人／名单{total}人' + (f'（{pending}人待绑定）' if pending else ''))
        if present - bound:
            lines.append(f'未分组已打卡：{len(present - bound)}人')
        lines.append(f'全群已打卡：{len(present)}人（每人只计一次）')
        return '\n'.join(lines)

    @staticmethod
    def work_window(now, cfg):
        def at(value):
            h, m = map(int, value.split(':'))
            return now.replace(hour=h, minute=m, second=0, microsecond=0)
        start, end = at(cfg['start']), at(cfg['end'])
        if end <= start:
            if now < start:
                start -= timedelta(days=1)
            else:
                end += timedelta(days=1)
        return start, end

    async def tick(self, bot, now=None, get_cfg=None):
        now = now or datetime.now(TZ)
        with self.connect() as db:
            chats = db.execute('SELECT cid,sent FROM chats').fetchall()
            db.execute('DELETE FROM events WHERE at<?', (int(now.timestamp()) - 86400,))
            db.execute('DELETE FROM punches WHERE at<?', (int(now.timestamp()) - 86400,))
        for cid, sent in chats:
            cfg = get_cfg(cid) if get_cfg else {'start':'09:55', 'end':'02:00', 'reset':'05:05', 'enabled':True}
            if not cfg.get('enabled', True):
                continue
            work_start, work_end = self.work_window(now, cfg)
            # Allow the scheduler's first tick at closing to deliver the final interval.
            if not work_start <= now < work_end + timedelta(seconds=60):
                continue
            day = work_start.strftime('%Y-%m-%d')
            with self.connect() as db:
                previous = db.execute('SELECT day FROM attendance_sent WHERE cid=?', (cid,)).fetchone()
            # Morning report is only sent in the opening minute, never as a late night catch-up.
            if work_start <= now < work_start + timedelta(seconds=60) and (not previous or previous[0] != day):
                h, m = map(int, cfg['reset'].split(':'))
                cutoff = work_start.replace(hour=h, minute=m)
                if cutoff > work_start:
                    cutoff -= timedelta(days=1)
                try:
                    await self.send(bot, cid, self.attendance_report(cid, cutoff, now))
                except Exception as exc:
                    print('上班统计发送失败', cid, type(exc).__name__, flush=True)
                else:
                    with self.connect() as db:
                        db.execute('INSERT OR REPLACE INTO attendance_sent VALUES (?,?)', (cid, day))
            end = min(hour(now), int(work_end.timestamp())) if now < work_end else int(work_end.timestamp())
            start = max(hour(datetime.fromtimestamp(end - 1, TZ)), int(work_start.timestamp()))
            if sent >= end or end <= start:
                continue
            text = self.report(cid, start, end)
            if sent < start and sent >= int(work_start.timestamp()):
                text += '\n提示：机器人曾停机或发送失败，本次仅汇总最近一个完整时段。'
            try:
                await self.send(bot, cid, text)
            except Exception as exc:
                print('小时统计发送失败', cid, type(exc).__name__, flush=True)
                continue
            with self.connect() as db:
                db.execute('UPDATE chats SET sent=? WHERE cid=?', (end, cid))
                db.execute('DELETE FROM events WHERE cid=? AND at<?', (cid, end))

    async def command(self, update, context):
        chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
        if chat.type not in ('group', 'supergroup') or not user or msg.sender_chat:
            return await msg.reply_text('请由群管理员使用个人账号在群内操作。')
        try:
            admin = await context.bot.get_chat_member(chat.id, user.id)
        except Exception:
            return await msg.reply_text('暂时无法验证管理员权限，请稍后重试。')
        if admin.status not in ('creator', 'administrator'):
            return await msg.reply_text('只有群管理员可以管理小组和查询测试报表。')
        cid = str(chat.id)
        cmd = msg.text.split()[0].split('@')[0]
        args = context.args
        try:
            if cmd == '/initgroups':
                fresh = self.initialize(cid, datetime.now(TZ))
                text = '已导入4组47人，开启工作时段整点统计及上班打卡人数统计。请回复成员消息发送 /setgroup 组名 名单姓名 进行绑定。' if fresh else '本群已初始化，保留现有名单和修改。'
            elif cmd == '/setgroup':
                if len(args) < 1:
                    raise ValueError('回复成员消息：/setgroup 金花组 金圣；手动添加待绑定名单：/setgroup 金花组 金圣')
                target = msg.reply_to_message
                if target and (target.sender_chat or not target.from_user or target.from_user.is_bot):
                    raise ValueError('请回复真实成员以个人身份发送的消息。')
                uid = str(target.from_user.id) if target else None
                name = ' '.join(args[1:]).strip() if len(args) > 1 else (target.from_user.full_name if target else '')
                if not name:
                    raise ValueError('请提供名单姓名，或回复成员消息。')
                self.set_member(cid, args[0], name, uid)
                text = f'已设置：{args[0]} / {name}，' + ('已绑定用户ID。' if uid else '待绑定（已有绑定会保留）。')
            elif cmd == '/delmember':
                target = msg.reply_to_message
                uid = str(target.from_user.id) if target and target.from_user and not target.sender_chat else None
                if not uid and not args:
                    raise ValueError('回复成员消息发送 /delmember，或 /delmember 名单姓名')
                count = self.remove(cid, name=' '.join(args), uid=uid)
                text = '已删除成员。已发生的离岗次数仍保留在当小时报表中。' if count else '未找到该成员。'
            elif cmd == '/groups':
                lines = ['【小组名单】']
                for team, name, uid in self.members(cid):
                    lines.append(f'{team}：{name} ' + (f'ID:{uid}' if uid else '待绑定'))
                text = '\n'.join(lines)
            elif cmd == '/hourlyreport':
                now = datetime.now(TZ)
                text = self.report(cid, hour(now), int(now.timestamp())) + '\n（本小时实时预览，不影响整点自动报表）'
            else:
                return
        except ValueError as exc:
            text = str(exc)
        await self.send(context.bot, cid, text)
