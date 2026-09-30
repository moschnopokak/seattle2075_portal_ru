"""Добавить Telegram ID игроку: python3 add-id.py <персонаж> <telegram_id> ["Имя игрока"]"""
import re
import sys

if len(sys.argv) < 3:
    sys.exit('Пример: python3 add-id.py hagane 919394189 "Имя"')
char, tg = sys.argv[1], sys.argv[2].strip()
name = sys.argv[3] if len(sys.argv) > 3 else None
if not tg.isdigit():
    sys.exit("Telegram ID должен состоять из цифр.")
path = "config/players.toml"
text = open(path, encoding="utf-8").read()
blocks = re.split(r"(?m)(?=^\[\[)", text)
for i, block in enumerate(blocks):
    if block.startswith("[[players]]") and re.search(r'characters\s*=\s*\[[^\]]*"%s"' % re.escape(char), block):
        def add(m):
            ids = [x.strip() for x in m.group(1).split(",") if x.strip()]
            if tg not in ids:
                ids.append(tg)
            return "telegram_ids = [%s]" % ", ".join(ids)
        block = re.sub(r"telegram_ids\s*=\s*\[(.*?)\]", add, block, count=1)
        if name:
            block = re.sub(r'name\s*=\s*".*?"', 'name = "%s"' % name.replace('"', ""), block, count=1)
        blocks[i] = block
        open(path, "w", encoding="utf-8").write("".join(blocks))
        print(block.strip())
        break
else:
    sys.exit("Персонаж %s не найден в players.toml" % char)
