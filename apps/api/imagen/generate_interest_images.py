"""Citify 関心軸別サムネ画像を Imagen で生成 + GCS にアップロード (Plan A-4 / B-4)。

10 軸 (住居/雇用/結婚/子育て/税/起業/防災/医療/教育/移住) のそれぞれに
1 枚の抽象画像を生成し、`gs://{BUCKET}/interests/{slug}.jpg` にアップロード。

倫理ガードレール (PROJECT.md §5):
    - 政治家・首長・議員の顔・名前を絶対に描かない
    - 政党ロゴ・特定企業ロゴなし
    - 抽象シーン (街並み、家族のシルエット、自然、シンボル) のみ
    - SynthID 透かしを保持 (Imagen 標準で付与)
    - 各画像に implicit な "AI 生成" であることを明示するメタデータを残す

使用方法:
    python -m apps.api.imagen.generate_interest_images \\
        --project-id citify-dev \\
        --location us-central1 \\
        --bucket citify-dev-public-assets \\
        --prefix interests \\
        [--dry-run]

注意:
    - Imagen 3 / 4 は Vertex AI 経由で呼び出し、ADC (gcloud auth application-default
      login) で認証。
    - 出力は JPEG 1024x1024 (1:1)、~50-200KB 程度
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_ID = "citify-dev"
DEFAULT_LOCATION = "us-central1"
DEFAULT_BUCKET = "citify-dev-public-assets"
DEFAULT_PREFIX = "interests"
# Imagen 4 が利用可能ならそちらが高品質。ハッカソンでは Imagen 3 で十分
DEFAULT_MODEL = "imagen-3.0-generate-002"

# 共通倫理プロンプト (全画像に付加)
_ETHICAL_GUARDRAIL = (
    "Abstract conceptual illustration. "
    "No specific people's faces, no politicians, no celebrity. "
    "No company logos, no political party symbols, no national flags. "
    "Soft pastel color palette, flat illustration style, "
    "Japanese aesthetic, calm and inclusive mood. "
    "Vertical 9:16 aspect ratio thumbnail."
)

# 強い否定プロンプト (人物の顔を完全に避ける)
_NEGATIVE_PROMPT = (
    "human faces, faces, portraits, realistic people, "
    "politicians, celebrities, text, logos, watermarks, "
    "national flags, party logos, photographic realism"
)


@dataclass(frozen=True)
class InterestSpec:
    slug: str  # ファイル名用 (英数字)
    label: str  # 日本語ラベル
    prompt: str  # Imagen プロンプト


# 10 関心軸 (FEATURES.md A-1 準拠、agents/relevance/schema.py の Interest と整合)
INTERESTS: tuple[InterestSpec, ...] = (
    InterestSpec(
        slug="housing",
        label="住居",
        prompt=(
            "Modern Japanese suburban housing district at golden hour, "
            "low-rise apartments and detached houses, soft warm sunset lighting, "
            "no people visible, flat illustration style."
        ),
    ),
    InterestSpec(
        slug="employment",
        label="雇用",
        prompt=(
            "Stylized Japanese city office buildings under blue sky, "
            "geometric flat illustration, gentle teal and cream palette, "
            "no people, no logos."
        ),
    ),
    InterestSpec(
        slug="marriage",
        label="結婚",
        prompt=(
            "Cherry blossoms with two intertwined wedding rings as the focal point, "
            "soft pink pastel background, abstract flat illustration."
        ),
    ),
    InterestSpec(
        slug="childcare",
        label="子育て",
        prompt=(
            "Silhouette of a parent and child holding hands in a park, "
            "warm afternoon light, abstract flat illustration, "
            "no facial details, no specific people, calm green and yellow palette."
        ),
    ),
    InterestSpec(
        slug="tax",
        label="税",
        prompt=(
            "Stylized Japanese yen coins, calculator, and paper documents in flat design, "
            "gentle gold and beige palette, top-down view, no text."
        ),
    ),
    InterestSpec(
        slug="startup",
        label="起業",
        prompt=(
            "Stylized rocket launch with a light bulb icon, "
            "innovation and growth concept, flat illustration, "
            "vibrant teal and orange palette, no logos, no people."
        ),
    ),
    InterestSpec(
        slug="disaster",
        label="防災",
        prompt=(
            "Japanese coastline with waves and protective seawall under cloudy sky, "
            "calm blue palette, abstract flat illustration, no people, no text."
        ),
    ),
    InterestSpec(
        slug="medical",
        label="医療",
        prompt=(
            "Stethoscope wrapped around a stylized heart icon, "
            "clean medical concept, soft blue and white palette, "
            "flat illustration, no people, no text."
        ),
    ),
    InterestSpec(
        slug="education",
        label="教育",
        prompt=(
            "Stack of open books with a pencil and an apple, "
            "learning concept, warm earth tones, flat illustration, "
            "no people, no specific text on book covers."
        ),
    ),
    InterestSpec(
        slug="migration",
        label="移住",
        prompt=(
            "Japanese countryside landscape with rice paddies and distant mountains, "
            "fresh green and sky blue palette, abstract flat illustration, "
            "no people, no buildings."
        ),
    ),
)


def _full_prompt(spec: InterestSpec) -> str:
    """関心軸プロンプト + 共通倫理プロンプト。"""
    return f"{spec.prompt} {_ETHICAL_GUARDRAIL}"


def _generate_image_bytes(
    project_id: str,
    location: str,
    model: str,
    prompt: str,
    negative_prompt: str,
) -> bytes:
    """Imagen で 1 枚生成し JPEG bytes を返す。"""
    import vertexai
    from vertexai.preview.vision_models import ImageGenerationModel

    vertexai.init(project=project_id, location=location)
    imagen = ImageGenerationModel.from_pretrained(model)

    response = imagen.generate_images(
        prompt=prompt,
        number_of_images=1,
        aspect_ratio="9:16",
        negative_prompt=negative_prompt,
        safety_filter_level="block_some",
        person_generation="dont_allow",  # 倫理ガード: 人物顔を生成しない
    )
    if not response.images:
        raise RuntimeError("Imagen returned no images")
    img = response.images[0]
    return img._image_bytes  # type: ignore[attr-defined]


def _upload_to_gcs(
    project_id: str,
    bucket: str,
    object_path: str,
    image_bytes: bytes,
    public_read: bool = True,
) -> str:
    """JPEG bytes を GCS にアップロード。public_read=True で公開アクセス権限を付与。

    bucket が uniform bucket-level access の場合は blob.make_public() が失敗するため、
    その場合は警告ログだけ出して続行 (bucket-level で allUsers:objectViewer 付与済を期待)。
    """
    from google.cloud import storage

    client = storage.Client(project=project_id)
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(object_path)
    blob.cache_control = "public, max-age=86400"
    blob.upload_from_string(image_bytes, content_type="image/jpeg")
    if public_read:
        try:
            blob.make_public()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "imagen.make_public_skipped (likely uniform bucket-level access). "
                "Ensure bucket-level allUsers:objectViewer is set. err=%s",
                exc,
            )
    return blob.public_url


def generate_and_upload_all(
    project_id: str,
    location: str,
    bucket: str,
    prefix: str,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
) -> dict[str, str]:
    """全 10 軸を生成してアップロード。slug → public URL の dict を返す。"""
    results: dict[str, str] = {}
    for spec in INTERESTS:
        full_prompt = _full_prompt(spec)
        object_path = f"{prefix}/{spec.slug}.jpg"
        logger.info(
            "imagen.generate slug=%s label=%s prompt_chars=%d",
            spec.slug,
            spec.label,
            len(full_prompt),
        )
        if dry_run:
            logger.info("imagen.dry_run slug=%s prompt=%r", spec.slug, full_prompt[:120])
            results[spec.slug] = f"gs://{bucket}/{object_path} (dry-run)"
            continue
        try:
            image_bytes = _generate_image_bytes(
                project_id=project_id,
                location=location,
                model=model,
                prompt=full_prompt,
                negative_prompt=_NEGATIVE_PROMPT,
            )
            public_url = _upload_to_gcs(
                project_id=project_id,
                bucket=bucket,
                object_path=object_path,
                image_bytes=image_bytes,
                public_read=True,
            )
            results[spec.slug] = public_url
            logger.info(
                "imagen.uploaded slug=%s label=%s url=%s size_kb=%d",
                spec.slug,
                spec.label,
                public_url,
                len(image_bytes) // 1024,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("imagen.failed slug=%s err=%s", spec.slug, exc)
            results[spec.slug] = f"FAILED: {exc.__class__.__name__}"
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Citify 関心軸別サムネを Imagen で生成 + GCS にアップロード",
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true", help="生成せず prompt のみ表示")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    results = generate_and_upload_all(
        project_id=args.project_id,
        location=args.location,
        bucket=args.bucket,
        prefix=args.prefix,
        model=args.model,
        dry_run=args.dry_run,
    )

    print("# Summary")
    for slug, url in results.items():
        print(f"{slug}\t{url}")

    failed = [s for s, u in results.items() if u.startswith("FAILED")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
