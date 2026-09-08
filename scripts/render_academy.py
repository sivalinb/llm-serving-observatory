"""Compile the reviewed curriculum to accessible static HTML (no backend required)."""

import json
import re
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def load_curriculum():
    data = json.loads((ROOT / "sites/curriculum.json").read_text())
    seen = set()
    for source in data["sources"].values():
        url = urlsplit(source["url"])
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("Invalid curriculum source URL")
    for lesson in data["lessons"]:
        if not re.fullmatch(r"[a-z][a-z0-9-]+", lesson["id"]) or lesson["id"] in seen:
            raise ValueError("Invalid or repeated lesson ID")
        if lesson["prerequisite"] and lesson["prerequisite"] not in seen:
            raise ValueError("Prerequisite must appear earlier in the learning path")
        if lesson["track"] not in data["tracks"]:
            raise ValueError("Unknown track")
        quiz = lesson["quiz"]
        if len(quiz["choices"]) != 3 or type(quiz["answer"]) is not int or not 0 <= quiz["answer"] < 3:
            raise ValueError("Invalid quiz choices or answer")
        for key in ["title", "summary", "signals", "pitfall", "exercise"]:
            if not lesson[key].strip():
                raise ValueError(f"Missing lesson {key}")
        if not lesson["concepts"] or not lesson["sources"]:
            raise ValueError("Missing concepts or sources")
        if not set(lesson["sources"]) <= data["sources"].keys():
            raise ValueError("Unknown primary source")
        seen.add(lesson["id"])
    return data


def render_academy():
    data = load_curriculum()
    h = escape
    cards = []
    for index, lesson in enumerate(data["lessons"], 1):
        key, quiz = lesson["id"], lesson["quiz"]
        concepts = ''.join(f'<dt>{h(c["term"])}</dt><dd>{h(c["detail"])}</dd>' for c in lesson["concepts"])
        sources = ' · '.join(
            f'<a href="{h(data["sources"][s]["url"])}" target="_blank" rel="noopener noreferrer">'
            f'{h(data["sources"][s]["title"])} ↗</a>' for s in lesson["sources"]
        )
        options = ''.join(
            f'<label><input type="radio" name="quiz-{key}" value="{i}"> {h(choice)}</label>'
            for i, choice in enumerate(quiz["choices"])
        )
        prerequisite = (
            f'<a href="#{lesson["prerequisite"]}">Previous module</a>'
            if lesson["prerequisite"] else '<span>Start here · no prerequisites</span>'
        )
        cards.append(f'''<details class="lesson" id="{key}" data-track="{h(lesson['track'])}">
<summary><span class="lesson-num">{index:02}</span><span><span class="lesson-track">{h(lesson['track'])}</span><strong>{h(lesson['title'])}</strong><span class="lesson-summary">{h(lesson['summary'])}</span></span><span class="expand-hint" aria-hidden="true">+</span></summary>
<div class="lesson-body"><div class="lesson-prereq">{prerequisite}<span>Concept + practice brief</span></div>
<dl class="concept-definitions">{concepts}</dl>
<div class="lesson-evidence"><section><h3>What to observe</h3><p>{h(lesson['signals'])}</p></section><section><h3>Common trap</h3><p>{h(lesson['pitfall'])}</p></section></div>
<section class="practice-brief"><h3>Practice it</h3><p>{h(lesson['exercise'])}</p></section>
<fieldset class="quiz" data-answer="{quiz['answer']}"><legend>Check your understanding: {h(quiz['question'])}</legend>{options}<button type="button" class="check-answer" hidden>Check answer</button><p class="quiz-result" role="status"></p><details class="answer-key"><summary>Explain the answer</summary><p>{h(quiz['choices'][quiz['answer']])} {h(quiz['explanation'])}</p></details></fieldset>
<p class="lesson-sources">Primary reading: {sources}</p></div></details>''')
    track_buttons = ''.join(
        f'<button type="button" data-track-filter="{h(track)}" aria-pressed="false">{h(track)}</button>'
        for track in data["tracks"]
    )
    page = (ROOT / "sites/academy.html").read_text()
    for placeholder, value in {
        "<!-- LESSONS -->": '\n'.join(cards), "<!-- TRACKS -->": track_buttons,
        "<!-- REVIEWED -->": h(data["reviewed"]),
    }.items():
        if page.count(placeholder) != 1:
            raise ValueError(f"Missing or repeated academy slot: {placeholder}")
        page = page.replace(placeholder, value)
    return page
