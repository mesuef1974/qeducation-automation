"""
تقييم ذاتي التصحيح للدرس: أسئلة من بنك الموضوع، بصيغة نصية يعدّلها المعلم قبل الاعتماد.
الصيغة (سطر لكل عنصر):
    س: نص السؤال            ← يبدأ سؤالًا جديدًا
    * الخيار الصحيح          ← اختيار من متعدد
    - خيار آخر
    = صح | = خطأ             ← صح أو خطأ
"""
from dataclasses import asdict, dataclass

MCQ, TF = "mcq", "tf"
TF_WORDS = {"صح": True, "صحيح": True, "خطأ": False, "خطا": False}
QUIZ_NAME = "تقييم الدرس"
POINTS = 1


@dataclass(frozen=True)
class Question:
    type: str
    text: str
    choices: tuple[str, ...] = ()
    correct: int = 0  # فهرس الخيار الصحيح (mcq)
    answer: bool = True  # (tf)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["choices"] = list(self.choices)
        return d


def quiz_name(position: int, title: str) -> str:
    return f"{QUIZ_NAME} {position}: {title}"


def to_text(questions: list[Question]) -> str:
    out = []
    for q in questions:
        out.append(f"س: {q.text}")
        if q.type == TF:
            out.append("= صح" if q.answer else "= خطأ")
        else:
            out.extend(("* " if i == q.correct else "- ") + c for i, c in enumerate(q.choices))
        out.append("")
    return "\n".join(out).strip()


def parse_text(text: str) -> list[Question]:
    """يحوّل نص المعلم إلى أسئلة ويرفض الناقص برسالة واضحة (ValueError)."""
    blocks: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("س:"):
            blocks.append({"text": line[2:].strip(), "choices": [], "correct": None, "answer": None})
        elif not blocks:
            raise ValueError("ابدأ كل سؤال بـ «س:»")
        elif line[0] in "*-" and line[1:2] == " ":
            b = blocks[-1]
            if line[0] == "*":
                if b["correct"] is not None:
                    raise ValueError(f"أكثر من إجابة صحيحة في: {b['text'][:30]}")
                b["correct"] = len(b["choices"])
            b["choices"].append(line[2:].strip())
        elif line.startswith("="):
            word = line[1:].strip()
            if word not in TF_WORDS:
                raise ValueError("بعد «=» اكتب صح أو خطأ")
            blocks[-1]["answer"] = TF_WORDS[word]
        else:
            raise ValueError(f"سطر غير مفهوم: {line[:40]}")
    questions = []
    for b in blocks:
        if not b["text"]:
            raise ValueError("سؤال بلا نص")
        if b["answer"] is not None and not b["choices"]:
            questions.append(Question(TF, b["text"], answer=b["answer"]))
        elif len(b["choices"]) >= 2 and b["correct"] is not None and b["answer"] is None:
            questions.append(Question(MCQ, b["text"], tuple(b["choices"]), b["correct"]))
        else:
            raise ValueError(f"سؤال ناقص (خياران على الأقل وإجابة واحدة بـ «*»، أو «= صح/خطأ»): {b['text'][:30]}")
    if not questions:
        raise ValueError("لا أسئلة")
    return questions


def from_dicts(items: list[dict]) -> list[Question]:
    return [Question(d["type"], d["text"], tuple(d.get("choices", ())), d.get("correct", 0), d.get("answer", True))
            for d in items]
