BEGIN TRANSACTION;
CREATE TABLE entries (id TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL);
INSERT INTO "entries" VALUES('7662fba9e24f','{"id": "7662fba9e24f", "type": "meet", "author": "gate", "status": "ok", "answers": {"rig": "да"}, "talk": "open", "stars": ["gate"], "created": 1790856975.0592983, "title": "Встреча у моста", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": ["gate", "rig"], "open": false, "where": "Мост", "cond": "Без оружия", "goal": "Договориться об оплате", "vis": "стол", "place": ""}',1.79085697505929827e+09);
INSERT INTO "entries" VALUES('d67c8c5e7735','{"id": "d67c8c5e7735", "type": "meet", "author": "gate", "status": "resched", "answers": {"rig": "нет", "hagane": "ждёт"}, "talk": "open", "stars": [], "created": 1790856975.100346, "title": "Дело с отказом", "from": "2075-08-06", "to": "2075-08-07", "tod": "вечер", "who": ["gate", "rig", "hagane"], "open": false, "where": "", "cond": "", "goal": "", "vis": "стол", "place": ""}',1.79085697510034608e+09);
INSERT INTO "entries" VALUES('5af07744e9b3','{"id": "5af07744e9b3", "type": "meet", "author": "hagane", "status": "reply", "answers": {"elijah": "ждёт"}, "talk": "open", "stars": [], "created": 1790856975.1161165, "title": "Личное дело Хаганэ", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": ["hagane", "elijah"], "open": false, "where": "", "cond": "", "goal": "Никому не рассказывать", "vis": "лично", "place": ""}',1.79085697511611652e+09);
INSERT INTO "entries" VALUES('cfdf6bddaeca','{"id": "cfdf6bddaeca", "type": "meet", "author": "rig", "status": "reply", "answers": {"gate": "ждёт", "hagane": "сам"}, "talk": "open", "stars": [], "created": 1790856975.1230216, "title": "Открытая запись", "from": "2075-08-10", "to": "2075-08-12", "tod": "вечер", "who": ["rig", "gate", "hagane"], "open": true, "where": "", "cond": "", "goal": "", "vis": "стол", "place": ""}',1.7908569751230216e+09);
INSERT INTO "entries" VALUES('f6ebb07643bb','{"id": "f6ebb07643bb", "type": "grow", "author": "rig", "status": "ok", "answers": {}, "talk": "open", "stars": [], "created": 1790856975.1429317, "title": "Навык взлома", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": ["rig"], "open": false, "where": "", "cond": "", "goal": "Повысить Hacking на 1", "vis": "стол", "place": "", "effect": "2075-08-10"}',1.79085697514293169e+09);
INSERT INTO "entries" VALUES('587ef3bf2ed7','{"id": "587ef3bf2ed7", "type": "grow", "author": "gate", "status": "gm", "answers": {}, "talk": "open", "stars": [], "created": 1790856975.1567879, "title": "Развитие на проверке", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": ["gate"], "open": false, "where": "", "cond": "", "goal": "Новая киберруки", "vis": "стол", "place": "", "effect": "2075-08-12"}',1.79085697515678787e+09);
INSERT INTO "entries" VALUES('a16e85851346','{"id": "a16e85851346", "type": "deal", "author": "alice", "status": "ok", "answers": {"karu": "да"}, "talk": "open", "stars": [], "created": 1790856975.1637163, "title": "Покупки Элис", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": ["alice", "karu"], "open": false, "where": "Любой магазин", "cond": "1000¥", "goal": "", "vis": "стол", "place": ""}',1.79085697516371631e+09);
INSERT INTO "entries" VALUES('8b7f2640a0ad','{"id": "8b7f2640a0ad", "type": "meet", "author": "gate", "status": "done", "answers": {"rig": "да"}, "talk": "open", "stars": [], "created": 1790856975.1711402, "title": "Давняя встреча", "from": "2075-07-22", "to": "2075-07-22", "tod": "вечер", "who": ["gate", "rig"], "open": false, "where": "", "cond": "", "goal": "", "vis": "стол", "place": ""}',1.79085697517114019e+09);
INSERT INTO "entries" VALUES('0c70ef5529f1','{"id": "0c70ef5529f1", "type": "meet", "author": "gm", "status": "ok", "answers": {"rig": "да", "gate": "да"}, "talk": "open", "stars": [], "created": 1790856975.1848137, "title": "Задание от мастера", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": ["rig", "gate"], "open": false, "where": "", "cond": "", "goal": "Общая цель", "vis": "стол", "place": ""}',1.79085697518481373e+09);
CREATE TABLE handout_files (
    token TEXT PRIMARY KEY, item_id TEXT NOT NULL, data BLOB NOT NULL, bytes INTEGER NOT NULL, raw_bytes INTEGER NOT NULL
);
INSERT INTO "handout_files" VALUES('2e2b79355f7102d0e9929a068f3e185f','hed561cbf',X'1F8B0800000000000203B3514CC94F2EA92C4855C828C9CDB1B3819049F9299540B6A1DD85F917765C6CBCD87361CF857D36FA40019B02A0D8C5860B3B2E6CBAB0F562938EC2850540F6E60B1B6CF40BEC6CF4211AF5C1A60000886FF35D5B000000',98,91);
CREATE TABLE items (
    kind TEXT NOT NULL, id TEXT NOT NULL, pos INTEGER NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
INSERT INTO "items" VALUES('windows','w1',0,'{"id": "w1", "from": "2075-07-01", "to": "2075-07-31", "name": "Арка 1", "gm": "Арка 1. СЕКРЕТ-название этапа"}');
INSERT INTO "items" VALUES('windows','w2',1,'{"id": "w2", "from": "2075-08-01", "to": "2075-08-31", "name": "Промежуточная арка", "inter": true}');
INSERT INTO "items" VALUES('windows','w3',2,'{"id": "w3", "from": "2075-09-01", "to": "2075-09-30", "name": "СЕКРЕТ-будущий этап", "gm": "СЕКРЕТ-имя будущего этапа"}');
INSERT INTO "items" VALUES('windows','wc41eb17e',3,'{"name": "Арка 2", "from": "2075-11-01", "to": "2075-11-30", "gm": "Арка 2: Крысы", "id": "wc41eb17e"}');
INSERT INTO "items" VALUES('rhythm','r1',0,'{"id": "r1", "wd": [0], "title": "Кофе по понедельникам", "note": "Общее", "vis": "стол"}');
INSERT INTO "items" VALUES('rhythm','r2',1,'{"id": "r2", "wd": [2], "title": "СЕКРЕТ-бои в яме", "note": "СЕКРЕТ-заметка ритма", "vis": "мастер"}');
INSERT INTO "items" VALUES('rhythm','r3adb43af',2,'{"title": "Пересменка", "note": "", "vis": "стол", "wd": [0, 3], "from": "2075-08-01", "to": "2075-12-31", "id": "r3adb43af"}');
INSERT INTO "items" VALUES('rhythm','rdfc39c2a',3,'{"title": "Привычка Рига", "note": "", "vis": "стол", "monthDay": 15, "who": "rig", "id": "rdfc39c2a"}');
INSERT INTO "items" VALUES('clocks','c1',0,'{"id": "c1", "title": "СЕКРЕТ-таймер", "note": "СЕКРЕТ-заметка таймера", "when": "2075-12-26"}');
INSERT INTO "items" VALUES('clocks','cff420e5b',1,'{"title": "Скрытый таймер", "note": "СЕКРЕТ: облава", "when": "2075-09-15", "id": "cff420e5b"}');
INSERT INTO "items" VALUES('plan','g1',0,'{"id": "g1", "from": "2075-08-10", "to": "2075-08-10", "title": "СЕКРЕТ-событие плана", "note": "СЕКРЕТ-описание плана", "session": ""}');
INSERT INTO "items" VALUES('plan','g2',1,'{"id": "g2", "from": "2075-08-12", "to": "2075-08-13", "title": "СЕКРЕТ-план с маской", "note": "СЕКРЕТ-описание плана с маской", "session": "", "cover": {"title": "Общий выходной", "note": "Ничего не планируйте", "who": ["rig", "gate"]}}');
INSERT INTO "items" VALUES('plan','gf35130ed',2,'{"title": "План налёта", "from": "2075-09-01", "to": "2075-09-02", "note": "СЕКРЕТ: детали", "session": "", "cover": {"title": "Общее событие", "note": "Город закрыт", "who": ["rig"]}, "id": "gf35130ed"}');
INSERT INTO "items" VALUES('past','p24e9a4bf',0,'{"title": "Хроника вручную", "from": "2075-07-15", "to": "2075-07-16", "note": "Публично", "session": "Сессия 1", "gm_note": "СЕКРЕТ", "id": "p24e9a4bf"}');
INSERT INTO "items" VALUES('past','p1',1,'{"id": "p1", "from": "2075-07-20", "to": "2075-07-20", "title": "Первая сессия", "note": "Публичная заметка", "session": "Арка 1, сессия 1", "gm_note": "СЕКРЕТ-заметка хроники", "plan_id": "g0"}');
INSERT INTO "items" VALUES('past','p592b031e',2,'{"id": "p592b031e", "from": "2075-07-20", "to": "2075-07-20", "title": "Сыгранный план", "note": "", "gm_note": "К переносу", "session": "", "plan_id": "gb91d5d20"}');
INSERT INTO "items" VALUES('places','m1',0,'{"id": "m1", "name": "Открытое место", "type": "home", "x": 1000, "y": 1000, "vis": "стол", "known": [], "note": "Видно всем", "gm_note": "СЕКРЕТ-заметка места 1"}');
INSERT INTO "items" VALUES('places','m2',1,'{"id": "m2", "name": "Место для знающих", "type": "contact", "x": 2000, "y": 2000, "vis": "знают", "known": ["rig"], "note": "Знает только Риг", "gm_note": "СЕКРЕТ-заметка места 2"}');
INSERT INTO "items" VALUES('places','m3',2,'{"id": "m3", "name": "СЕКРЕТ-скрытое место", "type": "danger", "x": 3000, "y": 3000, "vis": "мастер", "known": [], "note": "", "gm_note": "СЕКРЕТ-заметка места 3"}');
INSERT INTO "items" VALUES('places','m328b1746',3,'{"name": "Бар «Тузы»", "type": "business", "x": 4100, "y": 5200, "vis": "знают", "known": ["rig"], "note": "ВидноРигу", "gm_note": "СЕКРЕТ", "id": "m328b1746"}');
INSERT INTO "items" VALUES('dossier','n1',0,'{"id": "n1", "name": "Открытая карточка", "alias": "", "type": "person", "role": "Фиксер", "stance": "contact", "org": "", "vis": "стол", "known": [], "met": ["rig"], "last_date": "2075-07-20", "last_place": "m1", "last_note": "Встретились", "facts": [{"id": "f1", "text": "Открытое сведение", "vis": "стол", "known": [], "truth": "СЕКРЕТ-поправка на самом деле"}, {"id": "f2", "text": "Сведение для Рига", "vis": "знают", "known": ["rig"], "truth": ""}, {"id": "f3", "text": "СЕКРЕТ-сведение только мастера", "vis": "мастер", "known": [], "truth": ""}], "gm_note": "СЕКРЕТ-заметка карточки", "img": ""}');
INSERT INTO "items" VALUES('dossier','n2',1,'{"id": "n2", "name": "Карточка для Гейта", "alias": "", "type": "org", "role": "", "stance": "unknown", "org": "", "vis": "знают", "known": ["gate"], "met": [], "last_date": "", "last_place": "m3", "last_note": "", "facts": [], "gm_note": "СЕКРЕТ-заметка карточки 2", "img": ""}');
INSERT INTO "items" VALUES('dossier','n3',2,'{"id": "n3", "name": "СЕКРЕТ-скрытая карточка", "alias": "", "type": "person", "role": "", "stance": "hostile", "org": "", "vis": "мастер", "known": [], "met": [], "last_date": "", "last_place": "", "last_note": "", "facts": [], "gm_note": "СЕКРЕТ-заметка карточки 3", "img": ""}');
INSERT INTO "items" VALUES('dossier','nd0af2e1c',3,'{"name": "Фиксер Ли", "alias": "Ли", "type": "person", "role": "Достаёт железо", "stance": "contact", "org": "Кенран-кай", "vis": "стол", "known": [], "met": ["rig"], "last_date": "2075-07-20", "last_place": "m328b1746", "last_note": "Встретились в баре", "facts": [{"id": "f1", "text": "Знает ход через канализацию", "vis": "стол", "known": [], "truth": "СЕКРЕТ", "date": "2075-07-20"}], "gm_note": "СЕКРЕТ: двойной агент", "id": "nd0af2e1c", "img": "9c1411b51caa150a1d1ab4ff0b90b091"}');
INSERT INTO "items" VALUES('handouts','hed561cbf',0,'{"title": "Письмо Танаки", "date": "2075-07-30", "vis": "знают", "known": ["rig"], "note": "Нашли в сейфе", "gm_note": "СЕКРЕТ", "place": "m328b1746", "id": "hed561cbf", "file": "2e2b79355f7102d0e9929a068f3e185f", "size": 91, "fname": "п.html", "uploaded": 1790856975}');
INSERT INTO "items" VALUES('dnotes','downtown',0,'{"id": "downtown", "text": "Центр города", "gm_text": "СЕКРЕТ: патрули"}');
CREATE TABLE logins (
    telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_seen REAL
);
INSERT INTO "logins" VALUES(1,'','dev',1.79085697502277159e+09);
INSERT INTO "logins" VALUES(101,'','dev',1.79085697505268645e+09);
INSERT INTO "logins" VALUES(102,'','dev',1.790856975030061e+09);
INSERT INTO "logins" VALUES(103,'','dev',1.79085697503692126e+09);
INSERT INTO "logins" VALUES(104,'','dev',1.7908569750422995e+09);
INSERT INTO "logins" VALUES(105,'','dev',1.79085697504745745e+09);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL, author TEXT NOT NULL,
    user_id INTEGER, text TEXT NOT NULL, ts REAL NOT NULL
);
INSERT INTO "messages" VALUES(1,'7662fba9e24f','rig',103,'Приду с Хаганэ, если не против 👍',1.79085697507511329e+09);
INSERT INTO "messages" VALUES(2,'7662fba9e24f','gate',102,'Договорились.
Встречаемся в восемь.',1.79085697508201718e+09);
INSERT INTO "messages" VALUES(3,'cfdf6bddaeca','rig',103,'Заходи',1.79085697513568854e+09);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO "meta" VALUES('cal_start','2075-07-01');
INSERT INTO "meta" VALUES('cal_end','2075-12-31');
INSERT INTO "meta" VALUES('now_date','2075-08-02');
INSERT INTO "meta" VALUES('now_tod','день');
INSERT INTO "meta" VALUES('quiet_until','2075-08-08');
INSERT INTO "meta" VALUES('seeded','1');
INSERT INTO "meta" VALUES('version','39');
INSERT INTO "meta" VALUES('seeded:places','1');
INSERT INTO "meta" VALUES('seeded:dnotes','1');
INSERT INTO "meta" VALUES('seeded:dossier','1');
INSERT INTO "meta" VALUES('migr:dossier-1','1');
CREATE TABLE portraits (
    token TEXT NOT NULL, size TEXT NOT NULL, card_id TEXT NOT NULL, data BLOB NOT NULL, bytes INTEGER NOT NULL,
    PRIMARY KEY (token, size)
);
INSERT INTO "portraits" VALUES('9c1411b51caa150a1d1ab4ff0b90b091','f','nd0af2e1c',X'52494646E40100005745425056503820D8010000D033009D012AE001E0013E552A9447A3A2A221200800700A89696EE177611EDC00001DFE43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFB64E43DF6C9C87BED9390F7DB2721EFAC000FEFFBB58FFFFD8B396C0BC7FFFFDD93FFED93FFED93FF708000000000000000000000000000000000000000000000000',492);
INSERT INTO "portraits" VALUES('9c1411b51caa150a1d1ab4ff0b90b091','t','nd0af2e1c',X'524946465A00000057454250565038204E000000F004009D012A600060003E552A9347A3A2A1A120E800700A896900760000169079CCBDC69EF26FA74E9D3A74E9D37C0000FEF14DAFFFEC59CB605E3FFFFBB27FFDB27FFDB27FEE10000000000000',98);
CREATE INDEX messages_entry ON messages(entry_id);
CREATE INDEX portraits_card ON portraits(card_id);
CREATE INDEX handout_files_item ON handout_files(item_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('messages',3);
COMMIT;
