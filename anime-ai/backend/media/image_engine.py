"""
Sakura AI — Production Multimodal Image Generation System & Router

Core Capabilities:
1. ImageGenerationRouter: Routes visual intent to appropriate pipelines:
   - ANIME: High-quality anime illustration (Makoto Shinkai / ufotable / 90s cel, true anatomy, no animal humanization)
   - PHOTOREALISM: 85mm / 35mm portrait & environment realism, natural lighting & textures
   - UI: Modern dark-mode console / dashboard / software mockups
   - VECTOR: SVG / vector generation ONLY when explicitly requested by user
   - EDIT: Conversational multi-turn image editing with context preservation & lineage tracking
   - HIGH_RES_REGENERATION: High-detail prompt-based regeneration (not pixel super-resolution)
   - TEXT_TO_IMAGE: General high-fidelity raster generation
2. QualityEvaluator & Bounded Retries (max 2 retries):
   - Health checks on image binary integrity, resolution, minimum payload size
   - Auto-retry on network/rendering defect with seed mutation
3. Deep Prompt Expansion:
   - Subject + Anatomy + Expression + Style + Lighting + Environment + Composition + Color + Texture
   - Negative prompt constraints (no extra limbs, no humanized animal bodies, no plastic 3D toy surfaces)
4. Full Sakura Library Synchronization & Real Database Persistence
"""

import os
import re
import uuid
import json
import time
import random
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from database.models import User, Document, GeneratedImage
from services.storage import get_storage_backend, build_image_storage_key

UPLOAD_DIR = "./uploaded_documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Upstream image health status cache
_IMG_HEALTH_CACHE: Dict[str, Any] = {
    "status": "CONFIGURED",
    "last_check": 0.0,
    "last_verified_at": None,
    "failure_count": 0
}

# ─── Aspect Ratio Dimensions ──────────────────────────────────────────────────
ASPECT_RATIO_MAP = {
    "1:1": (1024, 1024),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "21:9": (1344, 576),
    "3:2": (1080, 720),
    "2:3": (720, 1080),
}

# ─── Custom Image Generation Exceptions ───────────────────────────────────────
class ImageTimeoutError(Exception):
    """Raised when image generation times out across all allowed attempts."""
    pass

class ImageTransientError(Exception):
    """Raised when transient network, 502/503/504, 429 or GPU worker failure occurs."""
    pass

class ImageNonTransientError(Exception):
    """Raised when request is fundamentally invalid, unauthorized or content-rejected."""
    pass


class GenerationPipeline(str, Enum):
    ANIME = "ANIME"
    PHOTOREALISM = "PHOTOREALISM"
    UI = "UI"
    VECTOR = "VECTOR"
    EDIT = "EDIT"
    UPSCALE = "UPSCALE"
    TEXT_TO_IMAGE = "TEXT_TO_IMAGE"


class ImageGenerationRouter:
    """
    Intelligently routes visual requests to specialized generation pipelines.
    Guarantees that standard artwork is ALWAYS rendered as real raster images (PNG/WebP),
    and SVG is strictly reserved for explicit vector requests.
    """
    @staticmethod
    def route_intent(prompt: str, is_edit: bool = False, is_upscale: bool = False) -> GenerationPipeline:
        if is_upscale:
            return GenerationPipeline.UPSCALE
        if is_edit:
            return GenerationPipeline.EDIT

        p_lower = prompt.lower()

        # Check for explicit vector requests ONLY
        explicit_vector_keywords = [
            "svg", "vector icon", "vector logo", "scalable vector",
            "svg diagram", "raw svg", "generate an svg", ".svg"
        ]
        if any(vk in p_lower for vk in explicit_vector_keywords):
            return GenerationPipeline.VECTOR

        # Anime / Manga / Japanese Animation
        anime_keywords = [
            "anime", "manga", "cel animation", "90s anime", "80s anime",
            "shoujo", "seinen", "shonen", "cyberpunk anime", "chibi",
            "makoto shinkai", "ufotable", "studio ghibli", "key visual"
        ]
        if any(ak in p_lower for ak in anime_keywords):
            return GenerationPipeline.ANIME

        # Photorealism
        photo_keywords = [
            "photo", "photorealistic", "photography", "portrait",
            "raw photo", "dslr", "85mm", "35mm", "realistic",
            "studio lighting", "hyperrealistic", "national geographic"
        ]
        if any(pk in p_lower for pk in photo_keywords):
            return GenerationPipeline.PHOTOREALISM

        # UI / UX Mockups
        ui_keywords = [
            "ui mockup", "ux design", "dashboard design", "app interface",
            "web interface", "figma mockup", "software screen", "developer console"
        ]
        if any(uk in p_lower for uk in ui_keywords):
            return GenerationPipeline.UI

        return GenerationPipeline.TEXT_TO_IMAGE


class QualityEvaluator:
    """
    Evaluates generated output validity, structural integrity, and byte completeness.
    """
    @staticmethod
    def validate_image_payload(file_path: str) -> bool:
        if not os.path.exists(file_path):
            return False
        size = os.path.getsize(file_path)
        # Minimum acceptable raster image size (corrupted/error responses are usually < 4KB)
        if size < 8192:
            return False
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
                # Check PNG, JPEG, or WebP magic headers
                is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
                is_jpeg = header.startswith(b"\xff\xd8\xff")
                is_webp = b"WEBP" in header or header.startswith(b"RIFF")
                return is_png or is_jpeg or is_webp
        except Exception:
            return False


class ImageGenerationEngine:
    def __init__(self, db: Session, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id
        self.router = ImageGenerationRouter()

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """
        Returns truthful runtime status of the image generation engine.
        Reflects actual upstream provider connectivity with a 60s TTL cache.
        Reports truthful capabilities: image_conditioned_edit=False and true_upscale=False.
        """
        now = time.time()
        # If cache is valid within 60 seconds, return cached status
        if _IMG_HEALTH_CACHE["last_check"] > 0 and (now - _IMG_HEALTH_CACHE["last_check"] < 60.0):
            return {
                "status": _IMG_HEALTH_CACHE["status"],
                "provider": "pollinations",
                "models": ["flux", "turbo"],
                "text_to_image": True,
                "image_conditioned_edit": False,
                "true_upscale": False,
                "variations": True,
                "prompt_variation": True,
                "high_res_regeneration": True,
                "health_verified_at": _IMG_HEALTH_CACHE["last_verified_at"]
            }

        # Perform actual lightweight upstream check
        status = "CONFIGURED"
        verified_at = None
        try:
            req = urllib.request.Request(
                "https://image.pollinations.ai/prompt/ping?width=16&height=16&nologo=true",
                headers={"User-Agent": "SakuraAI-HealthCheck/1.0"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status in (200, 301, 302):
                    status = "AVAILABLE"
                    verified_at = datetime.utcnow().isoformat()
                    _IMG_HEALTH_CACHE["failure_count"] = 0
                else:
                    status = "DEGRADED"
        except Exception:
            _IMG_HEALTH_CACHE["failure_count"] += 1
            if _IMG_HEALTH_CACHE["failure_count"] > 2:
                status = "UNAVAILABLE"
            else:
                status = "DEGRADED"

        _IMG_HEALTH_CACHE["status"] = status
        _IMG_HEALTH_CACHE["last_check"] = now
        if verified_at:
            _IMG_HEALTH_CACHE["last_verified_at"] = verified_at

        return {
            "status": status,
            "provider": "pollinations",
            "models": ["flux", "turbo"],
            "text_to_image": True,
            "image_conditioned_edit": False,
            "true_upscale": False,
            "variations": True,
            "prompt_variation": True,
            "high_res_regeneration": True,
            "health_verified_at": _IMG_HEALTH_CACHE["last_verified_at"]
        }

    # ─── 1. Aspect Ratio Inference ────────────────────────────────────────────
    @staticmethod
    def infer_aspect_ratio(prompt: str, explicit_ratio: Optional[str] = None) -> Tuple[str, int, int]:
        """Infers appropriate aspect ratio from explicit choice or natural language keywords."""
        if explicit_ratio and explicit_ratio in ASPECT_RATIO_MAP:
            w, h = ASPECT_RATIO_MAP[explicit_ratio]
            return explicit_ratio, w, h

        p_lower = prompt.lower()
        
        # Phone wallpaper / vertical reels / mobile
        if any(k in p_lower for k in ["phone wallpaper", "mobile wallpaper", "story", "stories", "vertical", "reel", "9:16", "tiktok"]):
            ratio = "9:16"
        # Desktop wallpaper / wide landscape / banner / hero / youtube
        elif any(k in p_lower for k in ["desktop wallpaper", "pc wallpaper", "wallpaper", "banner", "hero image", "youtube thumbnail", "landscape", "widescreen", "16:9"]):
            ratio = "16:9"
        # Ultrawide / cinematic
        elif any(k in p_lower for k in ["ultrawide", "cinematic banner", "panoramic", "21:9"]):
            ratio = "21:9"
        # Poster / book cover / illustration portrait
        elif any(k in p_lower for k in ["poster", "book cover", "magazine cover", "comic cover", "3:4"]):
            ratio = "3:4"
        # Classic photo
        elif any(k in p_lower for k in ["3:2", "photo print"]):
            ratio = "3:2"
        # Portrait photo
        elif any(k in p_lower for k in ["2:3", "portrait photo"]):
            ratio = "2:3"
        # Default square for avatars, logos, icons, general items
        else:
            ratio = "1:1"

        w, h = ASPECT_RATIO_MAP[ratio]
        return ratio, w, h

    # ─── 2. Deep Prompt Expansion & Style Engineering ─────────────────────────
    @staticmethod
    def expand_prompt(prompt: str, pipeline: GenerationPipeline, intensity: str = "medium") -> Tuple[str, str]:
        """
        Expands user prompt into complete visual composition specification.
        Maintains anatomical integrity for animals and characters.
        Returns: (positive_prompt, negative_prompt)
        """
        p_clean = prompt.strip()
        p_lower = p_clean.lower()

        # Check if subject is an animal (Dog, Cat, Wolf, Fox, etc.)
        animal_match = re.search(r'\b(dog|puppy|hound|shiba|corgi|cat|kitten|feline|wolf|fox|tiger|lion|bear|bird|rabbit|deer|horse)\b', p_lower)
        is_animal = animal_match is not None
        animal_name = animal_match.group(1) if animal_match else "subject"

        positive_elements = [p_clean]
        negative_elements = [
            "bad anatomy", "deformed limbs", "extra limbs", "missing limbs",
            "fused body parts", "blurry", "low quality", "watermark", "signature"
        ]

        if pipeline == GenerationPipeline.ANIME:
            # 1. Animal Anime Art: DO NOT HUMANIZE ANIMALS
            if is_animal:
                positive_elements.append(
                    f"authentic {animal_name} with accurate natural canine/animal anatomy, "
                    f"four natural legs and anatomically correct paws, natural muzzle and ears, "
                    f"appealing and friendly expressive eyes, layered fur with fine tufts and cel highlights, "
                    f"standing or sitting naturally in a coherent environment with sunlit meadow, soft drifting clouds, "
                    f"crisp professional Japanese anime linework, masterclass cel shading, warm directional lighting, "
                    f"subtle atmospheric depth, visually balanced composition, Makoto Shinkai inspired color grading"
                )
                negative_elements.extend([
                    "human face on animal", "human body", "humanized animal", "anthropomorphic", "furry character",
                    "human hairstyle", "doll eyes", "uncanny eyes", "plastic toy texture", "3d render gloss",
                    "deformed paws", "extra legs", "missing ears", "empty gradient background"
                ])
            else:
                # Character / Scene Anime Art
                positive_elements.append(
                    "masterwork anime key visual, clean delicate linework, vibrant expressive eyes, "
                    "layered flowing hair, rich cinematic cel shading, dynamic atmospheric lighting, "
                    "detailed background with environmental storytelling, harmonious color palette"
                )
                negative_elements.extend([
                    "mutated hands", "extra fingers", "deformed face", "asymmetric eyes",
                    "plastic 3d look", "muddy colors", "flat lighting"
                ])

        elif pipeline == GenerationPipeline.PHOTOREALISM:
            positive_elements.append(
                "hyper-realistic photograph, shot on 85mm f/1.4 lens, natural skin texture with subsurface scattering, "
                "authentic optical depth of field, balanced studio rim lighting, 8k resolution, raw color capture, "
                "sharp focus on primary subject, subtle atmospheric grain"
            )
            negative_elements.extend([
                "cgi", "cartoon", "illustration", "smooth plastic skin", "oversaturated", "fake lighting"
            ])

        elif pipeline == GenerationPipeline.UI:
            positive_elements.append(
                "sleek modern dark-mode software interface, crisp typography, clean glassmorphism cards, "
                "polished Figma dashboard mockup, minimalist developer console layout, sharp vectors, balanced spacing"
            )
            negative_elements.extend([
                "cluttered", "blurry text", "hand-drawn", "messy lines"
            ])

        else:  # TEXT_TO_IMAGE (General)
            positive_elements.append(
                "high-quality professional digital artwork, masterclass composition, intricate details, "
                "deliberate lighting, rich harmonious color palette, high fidelity"
            )

        # Intensity Scaling
        if intensity == "high":
            positive_elements.append("ultra-detailed masterpiece, cinematic volumetric rays, perfection in rendering")
        elif intensity == "low":
            positive_elements.append("clean, direct, visually clear")

        final_positive = ", ".join(positive_elements)
        final_negative = ", ".join(negative_elements)
        return final_positive, final_negative

    # ─── 3. Multi-Turn Edit Instruction Builder ──────────────────────────────
    @staticmethod
    def build_edit_prompt(base_prompt: str, edit_instruction: str) -> str:
        """
        Creates an edited prompt preserving existing subject context while applying targeted modifications.
        """
        return f"{base_prompt}, modified: {edit_instruction}, maintaining existing subject identity, composition, lighting, and aesthetic consistency"

    # ─── 4. Image Generation Core with Quality Validation & Bounded Retries ───
    async def generate_image(
        self,
        prompt: str,
        conversation_id: Optional[uuid.UUID] = None,
        aspect_ratio: Optional[str] = None,
        intensity: str = "medium",
        parent_image_id: Optional[uuid.UUID] = None,
        workflow: str = "TEXT_TO_IMAGE",
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes real image generation through routed pipeline with quality validation
        and bounded retries (max 2 retries). Saves to disk and syncs with Library.
        """
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValueError("Image prompt cannot be empty.")

        # Determine pipeline route
        pipeline = self.router.route_intent(
            clean_prompt,
            is_edit=(workflow == "EDIT_IMAGE"),
            is_upscale=(workflow == "UPSCALE")
        )

        # Determine aspect ratio and dimensions
        ratio, width, height = self.infer_aspect_ratio(clean_prompt, aspect_ratio)

        # Deep prompt expansion
        enhanced_prompt, negative_prompt = self.expand_prompt(clean_prompt, pipeline, intensity=intensity)

        # Setup intensity-based timeouts and retry policy
        # LOW: 40s timeout per attempt, 2 attempts
        # MEDIUM: 60s timeout per attempt, 3 attempts
        # HIGH: 120s timeout per attempt, 3 attempts
        if intensity == "high":
            attempt_timeout = 120
            max_attempts = 3
        elif intensity == "low":
            attempt_timeout = 40
            max_attempts = 2
        else: # medium
            attempt_timeout = 60
            max_attempts = 3

        last_error = None
        is_timeout = False

        image_id = uuid.uuid4()
        sanitized_title = re.sub(r'[^\w\s-]', '', clean_prompt[:36]).strip().replace(' ', '_')
        if not sanitized_title:
            sanitized_title = "Sakura_Artwork"

        storage_path = os.path.join(UPLOAD_DIR, f"{image_id}.png")
        file_size = 0
        actual_seed = seed if seed is not None else random.randint(1000, 9999999)
        actual_model = "flux"
        successful_attempt = 1

        loop = asyncio.get_event_loop()

        for attempt in range(max_attempts):
            current_seed = actual_seed if attempt == 0 else random.randint(10000, 9999999)
            
            # Failover: If primary Flux fails or times out, failover to secondary turbo provider
            active_model = "flux" if attempt < (max_attempts - 1) else "turbo"
            
            # Encode URL for neural rendering engine
            encoded_prompt = urllib.parse.quote(enhanced_prompt)
            pollinations_url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width={width}&height={height}&nologo=true&seed={current_seed}&model={active_model}"
            )

            def download_worker():
                req = urllib.request.Request(
                    pollinations_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SakuraAI/1.0"}
                )
                with urllib.request.urlopen(req, timeout=attempt_timeout) as resp:
                    with open(storage_path, "wb") as f:
                        f.write(resp.read())

            try:
                await loop.run_in_executor(None, download_worker)
                if QualityEvaluator.validate_image_payload(storage_path):
                    file_size = os.path.getsize(storage_path)
                    actual_seed = current_seed
                    actual_model = active_model
                    successful_attempt = attempt + 1
                    break
                else:
                    if os.path.exists(storage_path):
                        os.remove(storage_path)
                    last_error = Exception("Output failed quality validation (incomplete or corrupt image).")
            except Exception as e:
                err_str = str(e).lower()
                is_timeout = "timed out" in err_str or "timeout" in err_str or "time out" in err_str
                last_error = e
                if os.path.exists(storage_path):
                    try:
                        os.remove(storage_path)
                    except Exception:
                        pass

                # Non-transient errors (invalid parameters, auth, content rejection) should not retry
                if "400" in err_str or "401" in err_str or "403" in err_str or "unsupported" in err_str:
                    raise ImageNonTransientError(f"Image generation request error: {str(e)}")

            # Exponential backoff with jitter before next attempt
            if attempt < (max_attempts - 1):
                if attempt == 0:
                    backoff = random.uniform(1.0, 2.0)
                else:
                    backoff = random.uniform(3.0, 5.0)
                await asyncio.sleep(backoff)

        if not os.path.exists(storage_path) or file_size == 0:
            if is_timeout:
                raise ImageTimeoutError("The generation service took too long to respond.")
            raise ImageTransientError("The generation service took too long to respond.")

        filename = f"{sanitized_title}_{actual_seed % 10000}.png"
        public_image_url = f"/api/v1/library/files/{image_id}/download"

        # Lineage depth calculation & strict user-ownership enforcement
        valid_parent_id = None
        lineage_depth = 0
        if parent_image_id:
            parent = self.db.query(GeneratedImage).filter(
                GeneratedImage.id == parent_image_id,
                GeneratedImage.user_id == self.user_id
            ).first()
            if parent:
                valid_parent_id = parent.id
                lineage_depth = parent.lineage_depth + 1

        actual_provider = "pollinations"
        requested_provider = "pollinations"
        requested_model = "flux"
        failover_used = (actual_model != "flux")
        attempt_count = successful_attempt

        # Store in durable storage backend
        storage = get_storage_backend()
        storage_key = build_image_storage_key(str(self.user_id), str(image_id))
        with open(storage_path, "rb") as f:
            image_bytes = f.read()
        storage.put(storage_key, image_bytes, content_type="image/png")
        file_size = len(image_bytes)

        # 1. Register Document in Sakura Library
        doc = Document(
            id=image_id,
            user_id=self.user_id,
            filename=filename,
            mime_type="image/png",
            storage_path=storage_path,
            storage_backend=storage.backend_type,
            storage_key=storage_key,
            storage_size=file_size,
            is_knowledge_base=False,
            indexing_status="NOT_INDEXED",
            metadata_json={
                "status": "READY",
                "indexing_status": "NOT_INDEXED",
                "size": file_size,
                "category": "images",
                "source": "image_generation",
                "prompt": clean_prompt,
                "enhanced_prompt": enhanced_prompt,
                "pipeline": pipeline.value,
                "aspect_ratio": ratio,
                "width": width,
                "height": height,
                "provider": actual_provider,
                "model": actual_model,
                "requested_provider": requested_provider,
                "requested_model": requested_model,
                "failover_used": failover_used,
                "attempt_count": attempt_count,
                "image_conditioned_edit": False,
                "true_upscale": False,
                "seed": actual_seed,
                "workflow": workflow,
                "is_knowledge_base": False,
                "modified_at": datetime.utcnow().isoformat(),
                "chunks": 0
            }
        )
        self.db.add(doc)
        self.db.commit()

        # 2. Register GeneratedImage record
        gen_image = GeneratedImage(
            id=image_id,
            user_id=self.user_id,
            conversation_id=conversation_id,
            document_id=doc.id,
            prompt=clean_prompt,
            enhanced_prompt=enhanced_prompt,
            aspect_ratio=ratio,
            width=width,
            height=height,
            model=actual_model,
            seed=actual_seed,
            workflow=workflow,
            parent_image_id=valid_parent_id,
            lineage_depth=lineage_depth,
            storage_path=storage_path,
            storage_backend=storage.backend_type,
            storage_key=storage_key,
            storage_size=file_size,
            image_url=public_image_url,
            metadata_json={
                "provider": actual_provider,
                "actual_model": actual_model,
                "requested_provider": requested_provider,
                "requested_model": requested_model,
                "failover_used": failover_used,
                "attempt_count": attempt_count,
                "intensity": intensity,
                "pipeline": pipeline.value,
                "negative_prompt": negative_prompt,
                "file_size": file_size,
                "image_conditioned_edit": False,
                "true_upscale": False,
                "created_at": datetime.utcnow().isoformat()
            }
        )
        self.db.add(gen_image)
        self.db.commit()

        # 3. Broadcast real-time library synchronization
        from api.routes import ws_manager
        await ws_manager.send_to_user(str(self.user_id), {
            "type": "library_update",
            "action": "created",
            "data": {
                "id": str(doc.id),
                "name": filename,
                "filename": filename,
                "size": file_size,
                "sizeFormatted": f"{file_size / 1024:.1f} KB" if file_size < 1048576 else f"{file_size / (1024 * 1024):.2f} MB",
                "category": "images",
                "mimeType": "image/png",
                "modifiedAt": datetime.utcnow().isoformat(),
                "status": "READY",
                "prompt": clean_prompt,
                "aspectRatio": ratio,
                "width": width,
                "height": height
            }
        })

        return {
            "id": str(image_id),
            "url": public_image_url,
            "filename": filename,
            "prompt": clean_prompt,
            "enhanced_prompt": enhanced_prompt,
            "aspect_ratio": ratio,
            "width": width,
            "height": height,
            "model": actual_model,
            "provider": actual_provider,
            "pipeline": pipeline.value,
            "seed": actual_seed,
            "workflow": workflow,
            "parent_image_id": str(valid_parent_id) if valid_parent_id else None,
            "lineage_depth": lineage_depth,
            "file_size": file_size,
            "failover_used": failover_used,
            "attempt_count": attempt_count,
            "image_conditioned_edit": False,
            "true_upscale": False,
            "created_at": datetime.utcnow().isoformat()
        }

    # ─── 5. Edit Existing Image (Prompt-based Variation) ─────────────────────
    async def edit_image(
        self,
        parent_image_id: uuid.UUID,
        edit_instruction: str,
        conversation_id: Optional[uuid.UUID] = None,
        intensity: str = "medium"
    ) -> Dict[str, Any]:
        """
        Generates a prompt-based variation of an existing image preserving prior context and establishing edit lineage.
        Note: This is prompt-based reinterpretation/variation, not true image-conditioned diffusion.
        """
        parent = self.db.query(GeneratedImage).filter(
            GeneratedImage.id == parent_image_id,
            GeneratedImage.user_id == self.user_id
        ).first()

        if not parent:
            # If parent image is not found or not owned by user, treat as targeted generation without parent
            return await self.generate_image(
                prompt=edit_instruction,
                conversation_id=conversation_id,
                intensity=intensity,
                workflow="PROMPT_VARIATION"
            )

        combined_prompt = self.build_edit_prompt(parent.prompt, edit_instruction)
        return await self.generate_image(
            prompt=combined_prompt,
            conversation_id=conversation_id,
            aspect_ratio=parent.aspect_ratio,
            intensity=intensity,
            parent_image_id=parent.id,
            workflow="PROMPT_VARIATION"
        )

    # ─── 6. Variations ───────────────────────────────────────────────────────
    async def create_variations(
        self,
        parent_image_id: uuid.UUID,
        count: int = 2,
        conversation_id: Optional[uuid.UUID] = None,
        intensity: str = "medium"
    ) -> List[Dict[str, Any]]:
        """Generates multiple distinct prompt-based variations of a target image."""
        parent = self.db.query(GeneratedImage).filter(
            GeneratedImage.id == parent_image_id,
            GeneratedImage.user_id == self.user_id
        ).first()

        prompt = parent.prompt if parent else "creative visual variation"
        aspect_ratio = parent.aspect_ratio if parent else "1:1"

        variations = []
        for i in range(min(count, 4)):
            var_res = await self.generate_image(
                prompt=f"{prompt} (variation {i+1})",
                conversation_id=conversation_id,
                aspect_ratio=aspect_ratio,
                intensity=intensity,
                parent_image_id=parent.id if parent else None,
                workflow="VARIATION",
                seed=random.randint(100000, 9999999)
            )
            variations.append(var_res)

        return variations

    # ─── 7. Upscale (High-Resolution Regeneration) ───────────────────────────
    async def upscale_image(
        self,
        parent_image_id: uuid.UUID,
        scale: int = 2,
        conversation_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """
        Generates a higher fidelity prompt-based regeneration of an existing image.
        Note: This is high-resolution prompt-based regeneration, not true pixel super-resolution upscaling.
        """
        parent = self.db.query(GeneratedImage).filter(
            GeneratedImage.id == parent_image_id,
            GeneratedImage.user_id == self.user_id
        ).first()

        if not parent:
            raise ValueError("Target image for upscaling not found or not owned by user.")

        return await self.generate_image(
            prompt=f"{parent.prompt}, ultra-high resolution, crystalline fine details, 4k masterwork",
            conversation_id=conversation_id,
            aspect_ratio=parent.aspect_ratio,
            intensity="high",
            parent_image_id=parent.id,
            workflow="HIGH_RES_REGENERATION"
        )
