"""Cikti sozlesmesi: LLM'den beklenen yapilandirilmis JSON ve tip tanimlari.

KURAL (gorev sarti): LLM'den yapilandirilmis JSON istenir ve DOGRULANIR.
Dogrulanamayan yanit SESSIZCE KABUL EDILMEZ — `SchemaError` yukselir; cagiran
taraf ya yeniden dener ya da o maddeyi "etiketlenemedi" olarak kaydeder.

Bulgu 8 ile bag: MAS hatalarinin ~%21'i dogrulama katmanindan gelir; bu yuzden
dogrulama "yumusak" degil KATI tutulur ve basarisizlik sayilir, yutulmaz.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from .rubric import DIMENSIONS, DIMENSION_ORDER


class SchemaError(ValueError):
    """LLM yaniti sozlesmeye uymuyor."""


@dataclass(frozen=True)
class DimensionResult:
    """Tek bir boyutun etiketi ve o boyuta ozgu guven."""

    label: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "confidence": round(self.confidence, 4)}


@dataclass
class CallUsage:
    """Bir LLM cagrisinin token/maliyet kaydi."""

    tokens_in: int = 0
    tokens_out: int = 0
    #: Dusunce token'lari. `tokens_out` bunu ZATEN ICERIR; ayri tutulmasinin
    #: sebebi "akil yurutme ne kadara mal oluyor" sorusunu olcebilmektir.
    tokens_reasoning: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    cached: int = 0

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out

    def add(self, other: "CallUsage") -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        self.tokens_reasoning += other.tokens_reasoning
        self.cost_usd += other.cost_usd
        self.calls += other.calls
        self.cached += other.cached

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cost_usd"] = round(self.cost_usd, 6)
        d["tokens_total"] = self.tokens_total
        return d


@dataclass
class ItemSegmentation:
    """Bir sorunun tam segmentasyon ciktisi — cikti sozlesmesinin govdesi."""

    question_id: str
    #: boyut adi -> DimensionResult
    labels: dict[str, DimensionResult]
    #: `dikkat_tuzagi == "var"` ise isaret edilen sikkin 0-tabanli indeksi.
    trap_choice_index: int | None
    #: Ayni sikkin metni (dogrulama `validate.py`'de METIN uzerinden yapilir).
    trap_choice_text: str | None
    rationale: str
    prompt_version: str
    model: str
    variant: str
    usage: CallUsage = field(default_factory=CallUsage)
    #: Cok ajanli varyantlarda ajan basina ham etiketler (uzlasma gostergesi icin).
    agent_labels: list[dict[str, str]] = field(default_factory=list)
    #: Modelin `reasoning_content` izi. AYRI bir alandir: sema dogrulamasina
    #: GIRMEZ ve `rationale` (modelin kendi yazdigi gerekce) ile KARISTIRILMAZ.
    #: Rapora tam metin degil uzunlugu yazilir (`reasoning_chars`).
    reasoning_content: str = ""

    def label(self, dimension: str) -> str:
        return self.labels[dimension].label

    def label_tuple(self) -> tuple[str, ...]:
        return tuple(self.labels[d].label for d in DIMENSION_ORDER)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "labels": {k: v.to_dict() for k, v in self.labels.items()},
            "trap_choice_index": self.trap_choice_index,
            "trap_choice_text": self.trap_choice_text,
            "rationale": self.rationale,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "variant": self.variant,
            "usage": self.usage.to_dict(),
            "agent_labels": self.agent_labels,
            "reasoning_chars": len(self.reasoning_content),
        }


# `{...}` bloguna kadar olan gevezeligi atmak icin (LLM'ler ```json cite ekler).
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Metinden tek bir JSON nesnesi cikarir.

    Once dogrudan `json.loads` denenir; olmazsa ilk `{` ile son `}` arasi alinir.
    Hicbiri tutmazsa `SchemaError` — sessiz kabul YOK.
    """
    if not text or not text.strip():
        raise SchemaError("LLM yaniti bos.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise SchemaError("Yanitta JSON nesnesi bulunamadi.") from None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise SchemaError(f"JSON ayristirilamadi: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaError("Kok deger JSON nesnesi olmali.")
    return data


def _coerce_confidence(raw: Any, dimension: str) -> float:
    if raw is None:
        # Guven verilmemisse KABUL ETME: sozlesme boyut basina guven istiyor.
        raise SchemaError(f"'{dimension}' icin guven (confidence) yok.")
    try:
        val = float(raw)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"'{dimension}' guveni sayi degil: {raw!r}") from exc
    if not 0.0 <= val <= 1.0:
        raise SchemaError(f"'{dimension}' guveni [0,1] disinda: {val}")
    return val


def parse_label_json(
    text: str,
    *,
    question_id: str,
    choices: list[str],
    prompt_version: str,
    model: str,
    variant: str,
    usage: CallUsage | None = None,
) -> ItemSegmentation:
    """Ham LLM metnini dogrulanmis `ItemSegmentation`'a cevirir.

    Dogrulanan her sey:
      * dort boyutun HEPSI var mi,
      * her etiket o boyutun izinli kumesinde mi,
      * guven [0,1] araliginda mi,
      * `dikkat_tuzagi == "var"` ise gecerli bir sik indeksi var mi,
      * gerekce bos degil mi.
    """
    data = extract_json(text)
    raw_labels = data.get("boyutlar")
    if not isinstance(raw_labels, dict):
        raise SchemaError("'boyutlar' alani yok ya da nesne degil.")

    labels: dict[str, DimensionResult] = {}
    for name in DIMENSION_ORDER:
        spec = DIMENSIONS[name]
        entry = raw_labels.get(name)
        if entry is None:
            raise SchemaError(f"Boyut eksik: {name}")
        if isinstance(entry, str):
            # Yalnizca etiket dondurulmus; guven zorunlu oldugundan reddedilir.
            raise SchemaError(f"'{name}' icin guven (confidence) yok.")
        if not isinstance(entry, dict):
            raise SchemaError(f"'{name}' nesne olmali, {type(entry).__name__} geldi.")
        label = entry.get("etiket")
        if not isinstance(label, str):
            raise SchemaError(f"'{name}.etiket' metin olmali.")
        label = label.strip()
        if label not in spec.labels:
            raise SchemaError(
                f"'{name}' icin gecersiz etiket {label!r}; "
                f"izinliler: {', '.join(spec.labels)}")
        conf = _coerce_confidence(entry.get("guven"), name)
        labels[name] = DimensionResult(label=label, confidence=conf)

    trap_index: int | None = None
    trap_text: str | None = None
    if labels["dikkat_tuzagi"].label == "var":
        raw_idx = data.get("tuzak_sik_index")
        if raw_idx is None:
            raise SchemaError(
                "dikkat_tuzagi='var' ama 'tuzak_sik_index' verilmemis.")
        try:
            trap_index = int(raw_idx)
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"'tuzak_sik_index' tamsayi olmali: {raw_idx!r}") from exc
        if not 0 <= trap_index < len(choices):
            raise SchemaError(
                f"'tuzak_sik_index' aralik disi: {trap_index} "
                f"(sik sayisi {len(choices)})")
        trap_text = choices[trap_index]
    elif data.get("tuzak_sik_index") not in (None, -1):
        raise SchemaError("dikkat_tuzagi='yok' iken 'tuzak_sik_index' verilemez.")

    rationale = data.get("gerekce")
    if not isinstance(rationale, str) or not rationale.strip():
        raise SchemaError("'gerekce' bos olamaz.")

    return ItemSegmentation(
        question_id=question_id,
        labels=labels,
        trap_choice_index=trap_index,
        trap_choice_text=trap_text,
        rationale=rationale.strip()[:400],
        prompt_version=prompt_version,
        model=model,
        variant=variant,
        usage=usage or CallUsage(),
    )


def response_template() -> str:
    """Isteme gomulecek ornek JSON iskeleti (tek dogruluk kaynagi burasi)."""
    boyutlar = ",\n".join(
        f'    "{name}": {{"etiket": "<{ "|".join(DIMENSIONS[name].labels) }>", '
        f'"guven": 0.0}}'
        for name in DIMENSION_ORDER
    )
    return (
        "{\n"
        '  "boyutlar": {\n'
        f"{boyutlar}\n"
        "  },\n"
        '  "tuzak_sik_index": <dikkat_tuzagi "var" ise 0-tabanli sik indeksi, '
        'aksi halde null>,\n'
        '  "gerekce": "<en fazla iki cumle>"\n'
        "}"
    )
