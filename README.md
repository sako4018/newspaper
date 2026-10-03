# Сутрешен вестник

Две версии на един и същ вестник:

| Папка | Какво е | Как подбира новините |
|---|---|---|
| [`claude/`](claude/README.md) | Всеки ден в 06:00 прави едностраничен Word (`.docx`) | Claude обобщава и оценява |
| [`lite/`](lite/) | HTML страница, без LLM, потребителят избира теми | правила и сходство на текста |

И двете ползват общата виртуална среда в `.venv` в корена:

```bash
python3 -m venv .venv
.venv/bin/pip install -r claude/requirements.txt -r lite/requirements.txt
```

- Claude версията: `.venv/bin/python claude/vestnik.py`
- Lite версията: `.venv/bin/python lite/lite.py --open` (при първо пускане пита какво да следиш)
