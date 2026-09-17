"""Deterministic parser for the Rezeptify structured recipe JSON format."""
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from models import RezeptIn, Zutat


FORMAT_VERSION = "rezeptify-recipe/v1"


class StructuredIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str | int | float | None = ""
    unit: str | None = ""
    name: str = Field(min_length=1)
    group: str | None = None


class StructuredRecipe(BaseModel):
    """Public file schema. English keys make files portable and predictable."""
    model_config = ConfigDict(extra="forbid")

    format: Literal[FORMAT_VERSION]
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    ingredients: list[StructuredIngredient] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    servings: int = Field(default=4, ge=1, le=1000)
    prep_minutes: int = Field(default=0, ge=0, le=10080)
    cook_minutes: int = Field(default=0, ge=0, le=10080)
    difficulty: Literal["leicht", "mittel", "schwer"] = "mittel"
    category: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list)
    source_url: str = Field(default="", max_length=500)
    image_url: str | None = Field(default=None, max_length=2000)
    calories_per_serving: int | None = Field(default=None, ge=0)

    @field_validator("title", "description", "category", "source_url", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps):
        cleaned = [step.strip() for step in steps if isinstance(step, str) and step.strip()]
        if not cleaned:
            raise ValueError("muss mindestens einen nicht-leeren Schritt enthalten")
        if len(cleaned) != len(steps):
            raise ValueError("darf keine leeren Schritte enthalten")
        return cleaned

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags):
        if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError("darf nur nicht-leere Textwerte enthalten")
        return [tag.strip() for tag in tags]


def _error_detail(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        lines.append(f"{field}: {item['msg']}")
    return "Ungültige Rezeptdatei: " + "; ".join(lines)


def parse_structured_recipe(data: bytes) -> tuple[RezeptIn, str | None]:
    """Parse a UTF-8 JSON file into the app's existing recipe input model."""
    try:
        raw = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(400, "Rezeptdatei muss UTF-8-kodiertes JSON sein")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Ungültiges JSON in Zeile {exc.lineno}, Spalte {exc.colno}: {exc.msg}")
    if not isinstance(raw, dict):
        raise HTTPException(400, "Ungültige Rezeptdatei: Das JSON-Wurzelelement muss ein Objekt sein")
    try:
        parsed = StructuredRecipe.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(422, _error_detail(exc))

    recipe = RezeptIn(
        titel=parsed.title,
        beschreibung=parsed.description,
        zutaten=[Zutat(menge="" if item.amount is None else str(item.amount),
                        einheit=item.unit or "", name=item.name, gruppe=item.group)
                  for item in parsed.ingredients],
        zubereitung="\n\n".join(parsed.steps),
        portionen=parsed.servings,
        zeit_vorb=parsed.prep_minutes,
        zeit_koch=parsed.cook_minutes,
        schwierigkeit=parsed.difficulty,
        kategorie=parsed.category,
        tags=parsed.tags,
        quelle_url=parsed.source_url,
        quelle_typ="datei-import",
        kalorien_pro_portion=parsed.calories_per_serving,
    )
    return recipe, parsed.image_url
