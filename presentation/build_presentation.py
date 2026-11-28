"""
Sakura AI — Academic Major Project Presentation Generator (19 Slides, 16:9 Widescreen)

Generates presentation/Sakura_AI_Academic_Presentation.pptx using python-pptx and Pillow.
Run from repository root:
    python presentation/build_presentation.py
"""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_PPTX = ROOT / "presentation" / "Sakura_AI_Academic_Presentation.pptx"
DIAG_DIR = ROOT / "presentation" / "generated_diagrams"
SHOT_DIR = ROOT / "docs" / "assets" / "screenshots"

# Cohesive Sakura Academic Palette (crisp light slides for lecture-hall readability + deep navy cover)
NAVY = RGBColor(15, 23, 42)        # #0F172A
SLATE_DARK = RGBColor(30, 41, 59)  # #1E293B
SLATE_TEXT = RGBColor(51, 65, 85)  # #334155
MUTED = RGBColor(100, 116, 139)    # #64748B
BG_LIGHT = RGBColor(248, 250, 252) # #F8FAFC
WHITE = RGBColor(255, 255, 255)
BORDER = RGBColor(226, 232, 240)   # #E2E8F0
SAKURA = RGBColor(225, 29, 72)     # #E11D48
SAKURA_SOFT = RGBColor(255, 241, 242)
BLUE = RGBColor(37, 99, 235)       # #2563EB
BLUE_SOFT = RGBColor(239, 246, 255)
TEAL = RGBColor(13, 148, 136)      # #0D9488
TEAL_SOFT = RGBColor(240, 253, 250)
AMBER = RGBColor(217, 119, 6)      # #D97706
AMBER_SOFT = RGBColor(255, 251, 235)
GREEN = RGBColor(22, 163, 74)      # #16A34A
GREEN_SOFT = RGBColor(240, 253, 244)

FONT_FAMILY = "Calibri"


def load_pil_font(size: int, bold: bool = False):
    candidates = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for fp in candidates:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def draw_box(draw, xy, title, lines, fill, outline, title_color=(15, 23, 42), body_color=(51, 65, 85), radius=14):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=3)
    f_title = load_pil_font(22, bold=True)
    f_body = load_pil_font(17, bold=False)
    cx = (x1 + x2) // 2
    draw.text((cx, y1 + 18), title, fill=title_color, font=f_title, anchor="mt")
    curr_y = y1 + 52
    for line in lines:
        draw.text((cx, curr_y), line, fill=body_color, font=f_body, anchor="mt")
        curr_y += 24


def draw_arrow(draw, p1, p2, color=(71, 85, 105), width=4, label=None, label_offset=(0, -16)):
    x1, y1 = p1
    x2, y2 = p2
    draw.line([p1, p2], fill=color, width=width)
    # Arrowhead
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    head_len = 14
    a1 = (x2 - head_len * math.cos(angle - 0.45), y2 - head_len * math.sin(angle - 0.45))
    a2 = (x2 - head_len * math.cos(angle + 0.45), y2 - head_len * math.sin(angle + 0.45))
    draw.polygon([(x2, y2), a1, a2], fill=color)
    if label:
        mx = (x1 + x2) // 2 + label_offset[0]
        my = (y1 + y2) // 2 + label_offset[1]
        f_lbl = load_pil_font(16, bold=True)
        bbox = draw.textbbox((mx, my), label, font=f_lbl, anchor="mm")
        draw.rounded_rectangle((bbox[0] - 6, bbox[1] - 3, bbox[2] + 6, bbox[3] + 3), radius=6, fill=(255, 255, 255), outline=(226, 232, 240), width=1)
        draw.text((mx, my), label, fill=color, font=f_lbl, anchor="mm")


def generate_architecture_diagram(path: Path):
    img = Image.new("RGB", (1600, 820), (248, 250, 252))
    d = ImageDraw.Draw(img)
    # Tier banners
    f_sec = load_pil_font(19, bold=True)
    d.rounded_rectangle((20, 20, 320, 790), radius=16, fill=(255, 255, 255), outline=(203, 213, 225), width=2)
    d.text((170, 42), "CLIENT & EDGE", fill=(100, 116, 139), font=f_sec, anchor="mt")

    d.rounded_rectangle((350, 20, 740, 790), radius=16, fill=(255, 255, 255), outline=(203, 213, 225), width=2)
    d.text((545, 42), "APPLICATION & WORKERS", fill=(100, 116, 139), font=f_sec, anchor="mt")

    d.rounded_rectangle((770, 20, 1170, 790), radius=16, fill=(255, 255, 255), outline=(203, 213, 225), width=2)
    d.text((970, 42), "DATA, QUEUE & STORAGE", fill=(100, 116, 139), font=f_sec, anchor="mt")

    d.rounded_rectangle((1200, 20, 1580, 790), radius=16, fill=(255, 241, 242), outline=(251, 113, 133), width=2)
    d.text((1390, 42), "ISOLATED SANDBOX & AI", fill=(190, 18, 60), font=f_sec, anchor="mt")

    # Column 1
    draw_box(d, (45, 95, 295, 255), "Browser (Next.js 14)", ["TypeScript / React 18", "Header-Only Bearer Auth", "SSE & WS Client Hooks"], (239, 246, 255), (37, 99, 235))
    draw_box(d, (45, 320, 295, 480), "Nginx TLS Proxy", ["TLS 1.2/1.3 & HSTS", "Unbuffered SSE Streams", "WebSocket Upgrade"], (241, 245, 249), (71, 85, 105))
    draw_box(d, (45, 550, 295, 720), "Next.js Server (:3000)", ["Static / SSR Pages", "images.unoptimized=true", "/api/* Proxy Rewrites"], (239, 246, 255), (37, 99, 235))

    # Column 2
    draw_box(d, (375, 95, 715, 275), "FastAPI Backend API (:8000)", ["8 Modular API Routers", "PyJWT HS256 & Tenant Guards", "Quotas, Rate Limits & /readiness"], (255, 241, 242), (225, 29, 72))
    draw_box(d, (375, 325, 715, 465), "Task & Image Workers", ["worker.py (Docs, Outbox, Export)", "image_worker.py (Idempotent Gen)", "Lease-Fenced CAS Claims"], (240, 253, 250), (13, 148, 136))
    draw_box(d, (375, 500, 715, 625), "Cron Scheduler", ["scheduler.py (IANA Timezones)", "Unique (task_id, scheduled_for)"], (240, 253, 250), (13, 148, 136))
    draw_box(d, (375, 655, 715, 765), "Coding Worker", ["coding/job_worker.py", "21-Tool Agent (Zero Docker Socket)"], (255, 251, 235), (217, 119, 6))

    # Column 3
    draw_box(d, (795, 95, 1145, 295), "PostgreSQL 15 + pgvector", ["32 Normalized ORM Tables", "11 Alembic Migrations", "vector(1536) + SKIP LOCKED", "Authoritative Job & Outbox State"], (239, 246, 255), (37, 99, 235))
    draw_box(d, (795, 345, 1145, 520), "Redis 7 (AOF / noeviction)", ["Fail-Closed Rate Limits", "Multi-Worker WS Pub/Sub", "Worker Wakeups & HMAC Nonces"], (255, 241, 242), (225, 29, 72))
    draw_box(d, (795, 570, 1145, 745), "Object Storage Backend", ["S3-Compatible (Boto3) / Local FS", "Tenant Key: users/<uid>/...", "Killable Subprocess Outbox Purge"], (240, 253, 244), (22, 163, 74))

    # Column 4
    draw_box(d, (1225, 95, 1555, 285), "Multi-Provider AI & Media", ["Groq / OpenAI / Anthropic", "Local Ollama (Fail-Closed Private)", "OpenAI Embeddings & Whisper", "Pollinations Raster / Tavily"], (241, 245, 249), (71, 85, 105))
    draw_box(d, (1225, 355, 1555, 535), "Remote Sandbox Executor", ["coding/sandbox_service.py (:9000)", "Sole /var/run/docker.sock Host", "X-Sandbox-Token + HMAC Check"], (255, 255, 255), (225, 29, 72))
    draw_box(d, (1225, 585, 1555, 765), "Ephemeral Docker Container", ["--user 1001:1001 (Non-Root)", "--network none | --cap-drop ALL", "2 CPU | 512 MB | 64 PIDs", "Single Workspace Mount Only"], (255, 255, 255), (190, 18, 60))

    # Arrows
    draw_arrow(d, (170, 255), (170, 320), (37, 99, 235), label="HTTPS/WSS", label_offset=(62, 0))
    draw_arrow(d, (170, 480), (170, 550), (71, 85, 105), label="/", label_offset=(22, 0))
    draw_arrow(d, (295, 380), (375, 190), (225, 29, 72), label="/api/*", label_offset=(-20, -22))
    draw_arrow(d, (715, 185), (795, 185), (37, 99, 235))
    draw_arrow(d, (715, 240), (795, 405), (225, 29, 72))
    draw_arrow(d, (715, 395), (795, 245), (13, 148, 136))
    draw_arrow(d, (715, 430), (795, 640), (22, 163, 74))
    draw_arrow(d, (715, 560), (795, 275), (13, 148, 136))
    # Route Coding Worker -> Remote Sandbox Executor cleanly along the bottom gutter (zero box overlap)
    d.line([(715, 755), (755, 755), (755, 778), (1186, 778), (1186, 455)], fill=(217, 119, 6), width=4)
    draw_arrow(d, (1186, 455), (1225, 455), (217, 119, 6))
    f_lbl = load_pil_font(15, bold=True)
    bbox = d.textbbox((970, 778), "HTTP + X-Sandbox-Token + HMAC", font=f_lbl, anchor="mm")
    d.rounded_rectangle((bbox[0] - 8, bbox[1] - 3, bbox[2] + 8, bbox[3] + 3), radius=6, fill=(255, 255, 255), outline=(217, 119, 6), width=2)
    d.text((970, 778), "HTTP + X-Sandbox-Token + HMAC", fill=(217, 119, 6), font=f_lbl, anchor="mm")
    draw_arrow(d, (1145, 185), (1225, 185), (71, 85, 105))
    draw_arrow(d, (1390, 535), (1390, 585), (190, 18, 60), label="docker run", label_offset=(65, 0))

    img.save(path)


def generate_rag_diagram(path: Path):
    img = Image.new("RGB", (1600, 760), (248, 250, 252))
    d = ImageDraw.Draw(img)
    f_sec = load_pil_font(20, bold=True)

    # Top: Ingestion
    d.rounded_rectangle((25, 25, 1575, 330), radius=16, fill=(255, 255, 255), outline=(203, 213, 225), width=2)
    d.text((55, 42), "1. ASYNCHRONOUS DOCUMENT INGESTION (Lease-Fenced Worker + Index Generation Guard)", fill=(37, 99, 235), font=f_sec)

    draw_box(d, (50, 95, 330, 295), "Upload & Storage", ["POST /library/upload", "Quota: 100 files/day", "Key: users/<uid>/...", "index_generation++"], (239, 246, 255), (37, 99, 235))
    draw_box(d, (410, 95, 710, 295), "Parser & Chunker", ["pdfplumber (PDF) / UTF-8", "800-char Chunk Window", "150-char Overlap", "Clean Text Extraction"], (240, 253, 250), (13, 148, 136))
    draw_box(d, (790, 95, 1130, 295), "EmbeddingManager", ["OpenAI text-embedding-3-small", "1536 Dimensions (30s Timeout)", "Unconfigured -> NULL Vector", "(Zero Fake Random Vectors)"], (255, 251, 235), (217, 119, 6))
    draw_box(d, (1210, 95, 1550, 295), "PostgreSQL pgvector", ["Verify index_generation Fence", "& deletion_status == ACTIVE", "Insert document_chunks", "Status -> READY"], (240, 253, 244), (22, 163, 74))

    draw_arrow(d, (330, 195), (410, 195), (37, 99, 235))
    draw_arrow(d, (710, 195), (790, 195), (13, 148, 136))
    draw_arrow(d, (1130, 195), (1210, 195), (217, 119, 6))

    # Bottom: Hybrid Retrieval + Routing
    d.rounded_rectangle((25, 370, 1575, 735), radius=16, fill=(255, 255, 255), outline=(251, 113, 133), width=2)
    d.text((55, 388), "2. PER-USER HYBRID RETRIEVAL & PRIVACY-AWARE LLM ROUTING", fill=(225, 29, 72), font=f_sec)

    draw_box(d, (50, 445, 340, 695), "Scoped Query Filter", ["Chat Query + Scope", "JOIN documents WHERE", "user_id = current_user.id", "AND deletion = ACTIVE"], (255, 241, 242), (225, 29, 72))
    draw_box(d, (420, 440, 740, 560), "Dense Semantic Search", ["pgvector Cosine Distance (<=>)", "Over 1536-d Vectors"], (239, 246, 255), (37, 99, 235))
    draw_box(d, (420, 585, 740, 705), "Lexical Okapi BM25", ["k1 = 1.5, b = 0.75", "Exact IDs, Symbols & Offline Fallback"], (240, 253, 250), (13, 148, 136))
    draw_box(d, (820, 465, 1120, 675), "Reciprocal Rank Fusion", ["RRF(d) = sum(1 / (k + rank_i))", "Scale-Invariant Merging", "Top-K Grounded Passages", "With Filename Citations"], (255, 251, 235), (217, 119, 6))
    draw_box(d, (1200, 445, 1550, 695), "LLMRouter (SSE Stream)", ["Transient-Only Failover", "Groq / OpenAI / Anthropic", "Private Mode -> Ollama ONLY", "(Fail-Closed No Cloud Leak)"], (255, 241, 242), (225, 29, 72))

    draw_arrow(d, (340, 530), (420, 500), (37, 99, 235))
    draw_arrow(d, (340, 610), (420, 645), (13, 148, 136))
    draw_arrow(d, (740, 500), (820, 540), (37, 99, 235))
    draw_arrow(d, (740, 645), (820, 600), (13, 148, 136))
    draw_arrow(d, (1120, 570), (1200, 570), (225, 29, 72))

    img.save(path)


def generate_sandbox_diagram(path: Path):
    img = Image.new("RGB", (1600, 760), (248, 250, 252))
    d = ImageDraw.Draw(img)
    f_sec = load_pil_font(20, bold=True)

    # Left: App & Worker Zone
    d.rounded_rectangle((25, 25, 560, 735), radius=16, fill=(255, 255, 255), outline=(37, 99, 235), width=2)
    d.text((55, 45), "UNPRIVILEGED APP / WORKER ZONE", fill=(37, 99, 235), font=f_sec)
    d.text((55, 76), "(Zero /var/run/docker.sock Access)", fill=(100, 116, 139), font=load_pil_font(17))

    draw_box(d, (55, 125, 530, 285), "FastAPI Coding API (api/coding.py)", ["Quota Check (50 tasks/day) & Owner Guard", "Enqueues coding_jobs (QUEUED)", "Streams coding_task_events via SSE"], (239, 246, 255), (37, 99, 235))
    draw_box(d, (55, 330, 530, 515), "Standalone Coding Worker", ["coding/job_worker.py (FOR UPDATE SKIP LOCKED)", "Lease Heartbeat + Cancel Flag Check", "21-Tool Agent (read, patch, search, git, test)", "Strips All Backend Secrets from Env"], (240, 253, 250), (13, 148, 136))
    draw_box(d, (55, 560, 530, 705), "Network Capability Issuer", ["User Approves Specific Command", "HMAC-SHA256 Signed Token", "Bound to Workspace + Command Hash + TTL"], (255, 251, 235), (217, 119, 6))

    # Right: Hardened Executor & Container Zone
    d.rounded_rectangle((650, 25, 1575, 735), radius=16, fill=(255, 241, 242), outline=(225, 29, 72), width=3)
    d.text((680, 45), "HARDENED SANDBOX EXECUTION BOUNDARY", fill=(190, 18, 60), font=f_sec)
    d.text((680, 76), "(Dedicated Host — Sole Service Mounting /var/run/docker.sock)", fill=(159, 18, 57), font=load_pil_font(17))

    draw_box(d, (680, 125, 1545, 320), "Remote Sandbox Executor (coding/sandbox_service.py :9000)", ["1. Constant-Time X-Sandbox-Token Verification", "2. Strict Workspace UUID & Symlink Traversal Rejection", "3. Network Requests Require Valid HMAC + Single-Use Redis Nonce (Fail-Closed)", "4. Timeout Watchdog -> docker kill + docker rm -f (0 Orphaned Containers in CI)"], (255, 255, 255), (225, 29, 72))

    draw_box(d, (680, 385, 1100, 700), "Ephemeral Non-Root Container", ["--rm --user 1001:1001 (UID 1001)", "--cap-drop ALL", "--security-opt no-new-privileges:true", "--cpus=2.0 | --memory=512m", "--pids-limit=64", "Stdout/Stderr Capped at 100k Chars"], (255, 255, 255), (190, 18, 60))
    draw_box(d, (1135, 385, 1545, 700), "Filesystem & Network Isolation", ["Bind Mount ONLY Target Workspace:", "/workspaces/<uuid>:/workspace:rw", "Sibling Workspaces Completely Invisible", "Default: --network none (Zero SSRF)", "Approved Only: --network bridge", "(Single Command, Nonce Consumed)"], (240, 253, 244), (22, 163, 74))

    draw_arrow(d, (292, 285), (292, 330), (37, 99, 235))
    draw_arrow(d, (530, 420), (680, 235), (225, 29, 72), label="POST /execute", label_offset=(0, -24))
    draw_arrow(d, (530, 625), (680, 275), (217, 119, 6), label="HMAC Token", label_offset=(12, 22))
    draw_arrow(d, (920, 320), (920, 385), (190, 18, 60))
    draw_arrow(d, (1320, 320), (1320, 385), (22, 163, 74))

    img.save(path)


def add_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_chrome(slide, title: str, subtitle: str, slide_num: int, total: int = 19):
    add_bg(slide, BG_LIGHT)
    # Top accent bar
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = SAKURA
    bar.line.fill.background()

    # Header text
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.25), Inches(11.8), Inches(0.55))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = title
    p.font.name = FONT_FAMILY
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = NAVY

    if subtitle:
        sb = slide.shapes.add_textbox(Inches(0.6), Inches(0.8), Inches(12.0), Inches(0.35))
        stf = sb.text_frame
        stf.margin_left = stf.margin_top = stf.margin_right = stf.margin_bottom = 0
        sp = stf.paragraphs[0]
        sp.text = subtitle
        sp.font.name = FONT_FAMILY
        sp.font.size = Pt(14)
        sp.font.color.rgb = MUTED

    # Divider line
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.18), Inches(12.133), Inches(0.02))
    line.fill.solid()
    line.fill.fore_color.rgb = BORDER
    line.line.fill.background()

    # Footer
    ft = slide.shapes.add_textbox(Inches(0.6), Inches(7.12), Inches(9.5), Inches(0.28))
    ftf = ft.text_frame
    fp = ftf.paragraphs[0]
    fp.text = "Sakura AI  |  Full-Stack Multi-Agent AI Workspace  |  Academic Major Project Evaluation"
    fp.font.name = FONT_FAMILY
    fp.font.size = Pt(10.5)
    fp.font.color.rgb = MUTED

    pn = slide.shapes.add_textbox(Inches(11.5), Inches(7.12), Inches(1.233), Inches(0.28))
    ptf = pn.text_frame
    pp = ptf.paragraphs[0]
    pp.alignment = PP_ALIGN.RIGHT
    pp.text = f"{slide_num} / {total}"
    pp.font.name = FONT_FAMILY
    pp.font.size = Pt(10.5)
    pp.font.bold = True
    pp.font.color.rgb = SAKURA


def add_card(slide, left, top, width, height, title, bullets, accent=BLUE, bg_color=WHITE, body_size=14.5):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    card.adjustments[0] = 0.04
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color
    card.line.color.rgb = BORDER
    card.line.width = Pt(1.2)

    strip = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top + 0.12), Inches(0.08), Inches(height - 0.24))
    strip.fill.solid()
    strip.fill.fore_color.rgb = accent
    strip.line.fill.background()

    tb = slide.shapes.add_textbox(Inches(left + 0.24), Inches(top + 0.14), Inches(width - 0.36), Inches(height - 0.24))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p0 = tf.paragraphs[0]
    p0.text = title
    p0.font.name = FONT_FAMILY
    p0.font.size = Pt(16.5)
    p0.font.bold = True
    p0.font.color.rgb = NAVY
    p0.space_after = Pt(6)

    for b in bullets:
        p = tf.add_paragraph()
        p.text = f"•  {b}"
        p.font.name = FONT_FAMILY
        p.font.size = Pt(body_size)
        p.font.color.rgb = SLATE_TEXT
        p.space_after = Pt(5)


def add_notes(slide, text: str):
    notes = slide.notes_slide.notes_text_frame
    notes.text = text


def build_deck():
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    arch_png = DIAG_DIR / "arch_overview.png"
    rag_png = DIAG_DIR / "rag_workflow.png"
    sandbox_png = DIAG_DIR / "sandbox_isolation.png"

    generate_architecture_diagram(arch_png)
    generate_rag_diagram(rag_png)
    generate_sandbox_diagram(sandbox_png)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # ── Slide 1: Title Slide ──────────────────────────────────────────────────
    s1 = prs.slides.add_slide(blank)
    add_bg(s1, NAVY)
    band = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.28), Inches(7.5))
    band.fill.solid()
    band.fill.fore_color.rgb = SAKURA
    band.line.fill.background()

    badge = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(0.85), Inches(3.8), Inches(0.45))
    badge.fill.solid()
    badge.fill.fore_color.rgb = RGBColor(51, 20, 38)
    badge.line.color.rgb = SAKURA
    btf = badge.text_frame
    bp = btf.paragraphs[0]
    bp.text = "FINAL-YEAR MAJOR PROJECT PRESENTATION"
    bp.alignment = PP_ALIGN.CENTER
    bp.font.name = FONT_FAMILY
    bp.font.size = Pt(12)
    bp.font.bold = True
    bp.font.color.rgb = RGBColor(253, 164, 175)

    tbox = s1.shapes.add_textbox(Inches(0.9), Inches(1.55), Inches(11.5), Inches(2.2))
    ttf = tbox.text_frame
    ttf.word_wrap = True
    tp = ttf.paragraphs[0]
    tp.text = "Sakura AI"
    tp.font.name = FONT_FAMILY
    tp.font.size = Pt(54)
    tp.font.bold = True
    tp.font.color.rgb = WHITE
    tp2 = ttf.add_paragraph()
    tp2.text = "A Full-Stack Multi-Agent AI Workspace with Hybrid Semantic RAG,\nDurable Multi-Worker Orchestration, and Isolated Docker Code Execution"
    tp2.font.name = FONT_FAMILY
    tp2.font.size = Pt(22)
    tp2.font.color.rgb = RGBColor(203, 213, 225)
    tp2.space_before = Pt(12)

    meta_card = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(4.35), Inches(11.5), Inches(2.35))
    meta_card.adjustments[0] = 0.05
    meta_card.fill.solid()
    meta_card.fill.fore_color.rgb = SLATE_DARK
    meta_card.line.color.rgb = RGBColor(51, 65, 85)
    mtf = meta_card.text_frame
    mtf.margin_left = Inches(0.35)
    mtf.margin_top = Inches(0.25)
    meta_lines = [
        ("Presented By:", "[Student Name]  |  Roll No.: [University Roll Number]"),
        ("Project Guide:", "[Faculty Guide Name, Designation]"),
        ("Department & College:", "[Department of Computer Science & Engineering, Institution Name]"),
        ("Academic Year & Repo:", "[Academic Year]  |  github.com/Abhiram-C-Divakaran/Sakura-AI"),
    ]
    for i, (k, v) in enumerate(meta_lines):
        mp = mtf.paragraphs[0] if i == 0 else mtf.add_paragraph()
        mp.space_after = Pt(8)
        r1 = mp.add_run()
        r1.text = f"{k}  "
        r1.font.name = FONT_FAMILY
        r1.font.size = Pt(15)
        r1.font.bold = True
        r1.font.color.rgb = RGBColor(253, 164, 175)
        r2 = mp.add_run()
        r2.text = v
        r2.font.name = FONT_FAMILY
        r2.font.size = Pt(15)
        r2.font.color.rgb = WHITE
    add_notes(s1, "Welcome evaluators. Introduce Sakura AI as a production-oriented multi-agent AI workspace focused on systems reliability, hybrid search, and secure container sandboxing.")

    # ── Slide 2: Project Introduction ─────────────────────────────────────────
    s2 = prs.slides.add_slide(blank)
    add_chrome(s2, "Project Introduction", "What Sakura AI is and why it goes beyond a conventional chatbot wrapper", 2)
    add_card(s2, 0.6, 1.45, 7.2, 5.3, "Unified Full-Stack AI Workspace", [
        "Brings conversational AI, document Q&A (Hybrid RAG), persistent memory, multimodal image generation, voice transcription, scheduled jobs, and autonomous code editing into one web app.",
        "Engineered as a multi-tenant web platform: Next.js 14 (TypeScript) frontend + FastAPI (Python 3.11+) backend + PostgreSQL 15 (pgvector) + Redis 7 + Docker.",
        "Built around real systems-engineering guarantees: ACID schema migrations, lease-fenced workers, strict per-user authorization, and non-root code sandboxing.",
        "Continuously verified across 253 local backend tests and 4 automated GitHub Actions CI workflows."
    ], accent=SAKURA, body_size=15.5)
    # Right KPI stack
    kpis = [
        ("32 Tables / 11 Migrations", "Normalized PostgreSQL 15 + pgvector(1536) schema", BLUE, BLUE_SOFT),
        ("4 Standalone Workers", "Task, Image, Coding & Timezone Cron Scheduler", TEAL, TEAL_SOFT),
        ("Isolated Docker Sandbox", "Non-root UID 1001, --network none, 0 orphans in CI", SAKURA, SAKURA_SOFT),
        ("4/4 Required CI Jobs", "Real PG15, Redis 7, Docker E2E & Playwright E2E", GREEN, GREEN_SOFT),
    ]
    for idx, (k, desc, col, bgc) in enumerate(kpis):
        add_card(s2, 8.05, 1.45 + idx * 1.35, 4.68, 1.2, k, [desc], accent=col, bg_color=bgc, body_size=13)
    add_notes(s2, "Highlight the shift from single-prompt chat demos to an integrated, multi-tenant platform backed by PostgreSQL, Redis, and Docker.")

    # ── Slide 3: Problem Statement ────────────────────────────────────────────
    s3 = prs.slides.add_slide(blank)
    add_chrome(s3, "Problem Statement", "Critical engineering gaps observed in conventional AI assistant prototypes", 3)
    probs = [
        ("1. Vendor Lock-In & Privacy Leakage", ["Single commercial API dependency causes downtime during outages.", "Naive fallbacks can silently send private prompts to external cloud APIs."], SAKURA),
        ("2. Brittle Search & Tenant Mixing", ["Dense-only vector search misses exact IDs, symbols, and error codes.", "Unpartitioned vector indices risk cross-user document leakage."], BLUE),
        ("3. Volatile In-Memory Background Jobs", ["Long-running uploads, image jobs, and file deletions inside web threads vanish on restart.", "Concurrent workers without lease fencing overwrite each other's state."], AMBER),
        ("4. Unsafe Host Code Execution & Auth Gaps", ["Running AI-generated commands on the host exposes secrets and sibling workspaces.", "Passing JWTs in URLs (?token=) leaks credentials into logs; missing quotas risk abuse."], TEAL),
    ]
    coords = [(0.6, 1.45), (6.8, 1.45), (0.6, 4.25), (6.8, 4.25)]
    for (x, y), (t, b, c) in zip(coords, probs):
        add_card(s3, x, y, 5.93, 2.55, t, b, accent=c, body_size=15)
    add_notes(s3, "Explain each of the four concrete engineering problems that motivated Sakura AI's architecture.")

    # ── Slide 4: Project Objectives ───────────────────────────────────────────
    s4 = prs.slides.add_slide(blank)
    add_chrome(s4, "Project Objectives", "Seven measurable engineering goals guiding Sakura AI's implementation", 4)
    objs = [
        ("Unified Workspace", "Deliver streaming chat, memory, library, images, audio, projects, scheduling, and coding in one responsive UI."),
        ("Provider-Neutral & Private", "Support Groq, OpenAI, Anthropic, and local Ollama with transient-only failover and fail-closed private mode."),
        ("Per-User Hybrid RAG", "Fuse PostgreSQL pgvector(1536) cosine similarity with Okapi BM25 via Reciprocal Rank Fusion (RRF)."),
        ("Crash-Safe Workers", "Store all jobs and storage deletions authoritatively in PostgreSQL with atomic claims and lease fencing."),
        ("Hardened Coding Sandbox", "Isolate AI-written code inside non-root, network-disabled Docker containers via a remote executor."),
        ("Multi-Tenant Governance", "Enforce PyJWT header-only auth, single-use WS tickets, Redis rate limits, daily quotas, and account deletion."),
        ("Reproducible Verification", "Prove correctness continuously with unit tests, PG15 concurrency, backup/restore, Docker, and Playwright CI."),
    ]
    for i, (ot, od) in enumerate(objs):
        col_i = 0 if i < 4 else 1
        row_i = i if i < 4 else i - 4
        x = 0.6 + col_i * 6.2
        y = 1.45 + row_i * 1.38
        w = 5.93
        h = 1.22
        add_card(s4, x, y, w, h, f"Objective {i + 1}: {ot}", [od], accent=SAKURA if i % 2 == 0 else BLUE, body_size=13.5)
    add_notes(s4, "Every objective directly maps to implemented backend/frontend modules and verifiable automated tests.")

    # ── Slide 5: Existing System ──────────────────────────────────────────────
    s5 = prs.slides.add_slide(blank)
    add_chrome(s5, "Existing Systems & Limitations", "Analysis of current AI assistant categories and their architectural trade-offs", 5)
    add_card(s5, 0.6, 1.5, 3.85, 5.2, "Commercial Closed Platforms", [
        "Examples: Hosted proprietary chat suites.",
        "Strength: Frontier model quality and polished UX.",
        "Limitation: Closed source, vendor lock-in, no self-hosted local-private Ollama boundary.",
        "Limitation: Limited customization for institutional databases and workflows."
    ], accent=BLUE, body_size=14.5)
    add_card(s5, 4.74, 1.5, 3.85, 5.2, "Lightweight Open-Source Wrappers", [
        "Examples: Minimal FastAPI/React LLM templates.",
        "Strength: Fast prototyping for single users.",
        "Limitation: In-memory background tasks lost on restart; no lease fencing.",
        "Limitation: Vector-only RAG, weak multi-tenant storage cleanup, URL token exposure."
    ], accent=AMBER, body_size=14.5)
    add_card(s5, 8.88, 1.5, 3.85, 5.2, "Local CLI Coding Agents", [
        "Examples: Terminal-based code editors.",
        "Strength: Direct access to local toolchains.",
        "Limitation: Executes with full host OS and network privileges.",
        "Limitation: Unsafe for multi-user hosted web applications without container isolation."
    ], accent=SAKURA, body_size=14.5)
    add_notes(s5, "Contrast the three existing categories honestly—acknowledging strengths while highlighting gaps in durability, hybrid retrieval, and multi-user sandboxing.")

    # ── Slide 6: Proposed System & Comparison ─────────────────────────────────
    s6 = prs.slides.add_slide(blank)
    add_chrome(s6, "Proposed System: Sakura AI", "Comparative architectural advantages over conventional solutions", 6)
    rows = [
        ["Capability", "Conventional Wrapper", "Sakura AI (Proposed System)"],
        ["LLM Routing", "Single hardcoded vendor", "Multi-provider (Groq, OpenAI, Anthropic, Ollama) + fail-closed private mode"],
        ["Document Search", "Vector-only or keyword-only", "Hybrid pgvector(1536) + Okapi BM25 + RRF, strictly per-user scoped"],
        ["Background Jobs", "Volatile in-memory threads", "PostgreSQL authoritative queues, FOR UPDATE SKIP LOCKED & lease fencing"],
        ["File Deletion", "Blocking sync delete / orphans", "HTTP 202 + StorageDeletionOutbox + killable subprocess runner"],
        ["Code Execution", "Host subprocess or none", "Remote sandbox-executor, UID 1001, --network none, HMAC capabilities"],
        ["Auth & Abuse", "Basic JWT / often ?token=", "PyJWT header-only auth, single-use WS tickets, Redis rate limits & daily quotas"],
    ]
    tbl_shape = s6.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.48), Inches(12.133), Inches(5.35))
    tbl = tbl_shape.table
    tbl.columns[0].width = Inches(2.3)
    tbl.columns[1].width = Inches(3.5)
    tbl.columns[2].width = Inches(6.333)
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = tbl.cell(r_idx, c_idx)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if r_idx == 0:
                cell.fill.fore_color.rgb = NAVY
            else:
                cell.fill.fore_color.rgb = WHITE if r_idx % 2 == 1 else RGBColor(241, 245, 249)
            p = cell.text_frame.paragraphs[0]
            p.text = val
            p.font.name = FONT_FAMILY
            p.font.size = Pt(14 if r_idx == 0 else 13.5)
            p.font.bold = (r_idx == 0 or c_idx == 0)
            p.font.color.rgb = WHITE if r_idx == 0 else (NAVY if c_idx == 0 else (TEAL if c_idx == 2 else SLATE_TEXT))
    add_notes(s6, "Walk through the comparison row by row, emphasizing how every row corresponds to verified code in the repository.")

    # ── Slide 7: Technology Stack ─────────────────────────────────────────────
    s7 = prs.slides.add_slide(blank)
    add_chrome(s7, "Technology Stack", "Actual technologies implemented across all architectural layers", 7)
    stack = [
        ("Frontend Layer", ["Next.js 14 & React 18", "TypeScript 5 (strict check)", "Tailwind CSS & Framer Motion", "Playwright Chromium E2E"], BLUE),
        ("Backend API & Auth", ["Python 3.11+ & FastAPI / Uvicorn", "SQLAlchemy 2 & Alembic (11 revs)", "Pydantic v2 Validation", "PyJWT (HS256) & Passlib pbkdf2"], SAKURA),
        ("Database & Search", ["PostgreSQL 15 + pgvector(1536)", "Okapi BM25 + RRF Retrieval", "pdfplumber Document Parsing", "SQLite Local Dev Parity"], TEAL),
        ("Queue, Cache & Storage", ["Redis 7 (AOF + noeviction)", "Pub/Sub WS Fan-Out & Nonces", "Boto3 S3-Compatible Storage", "LocalFilesystemStorage"], AMBER),
        ("AI & Media Providers", ["Groq, OpenAI, Anthropic, Ollama", "OpenAI text-embedding-3-small", "OpenAI Whisper Transcription", "Pollinations Raster & Tavily"], BLUE),
        ("Isolation & DevOps", ["Docker & Docker Compose (10 svcs)", "Non-Root Sandbox (UID 1001)", "Nginx TLS 1.2/1.3 Proxy", "GitHub Actions (4 Required Jobs)"], GREEN),
    ]
    positions = [(0.6, 1.45), (4.74, 1.45), (8.88, 1.45), (0.6, 4.25), (4.74, 4.25), (8.88, 4.25)]
    for (x, y), (t, b, c) in zip(positions, stack):
        add_card(s7, x, y, 3.85, 2.55, t, b, accent=c, body_size=14)
    add_notes(s7, "Explain why each technology was selected: FastAPI for async SSE/WS, PostgreSQL+pgvector for ACID vector+relational integrity, Redis for atomic counters/PubSub, Docker for sandbox isolation.")

    # ── Slide 8: System Architecture ──────────────────────────────────────────
    s8 = prs.slides.add_slide(blank)
    add_chrome(s8, "System Architecture", "10-service production topology separating API, durable workers, data, and Docker sandbox", 8)
    pic8 = s8.shapes.add_picture(str(arch_png), Inches(0), Inches(1.32), height=Inches(5.6))
    pic8.left = int((prs.slide_width - pic8.width) / 2)
    add_notes(s8, "Walk left to right: Browser -> Nginx -> Next.js/FastAPI -> PostgreSQL/Redis/Storage -> 4 independent workers -> isolated sandbox-executor mounting docker.sock exclusively.")

    # ── Slide 9: Database Architecture ────────────────────────────────────────
    s9 = prs.slides.add_slide(blank)
    add_chrome(s9, "Database Architecture (32 Tables, 11 Migrations)", "PostgreSQL 15 + pgvector schema managed strictly via Alembic with SQLite dev parity", 9)
    domains = [
        ("Identity & Governance (6)", ["users, password_reset_tokens", "websocket_tickets, user_usage_quotas", "user_data_exports, account_audit_events"], SAKURA),
        ("Conversations & Memory (6)", ["characters, conversations, messages", "message_feedbacks, conversation_shares", "user_memories"], BLUE),
        ("Documents & Outbox (3)", ["documents (index_generation, deletion_status)", "document_chunks (embedding vector(1536))", "storage_deletion_outbox (claim_token, lease)"], TEAL),
        ("Projects & Integrations (5)", ["projects, project_conversations", "project_files, project_repositories", "user_integrations (Fernet encrypted)"], AMBER),
        ("Multimodal Media (3)", ["generated_images (parent_image_id lineage)", "image_generation_jobs (lease fenced)", "image_variation_batches (fingerprint)"], BLUE),
        ("Workers & Coding Engine (9)", ["background_tasks, scheduled_tasks, runs", "repository_workspaces, coding_jobs, tasks", "coding_task_events, tool_executions, net_auth"], GREEN),
    ]
    for (x, y), (t, b, c) in zip(positions, domains):
        add_card(s9, x, y, 3.85, 2.35, t, b, accent=c, body_size=13.2)
    banner = s9.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.6), Inches(6.35), Inches(12.133), Inches(0.6))
    banner.fill.solid()
    banner.fill.fore_color.rgb = NAVY
    banner.line.fill.background()
    bp = banner.text_frame.paragraphs[0]
    bp.alignment = PP_ALIGN.CENTER
    bp.text = "Alembic HEAD: j9f7a263b56c  |  Dialect-Aware Vector(1536) (PG native / SQLite JSON)  |  Verified 32/32 Schema Parity & pg_restore Checksum Tests in CI"
    bp.font.name = FONT_FAMILY
    bp.font.size = Pt(13)
    bp.font.bold = True
    bp.font.color.rgb = WHITE
    add_notes(s9, "Emphasize that every table is real and verified by test_schema_parity.py, and point out why account_audit_events intentionally omits a cascading FK to users.")

    # ── Slide 10: Major Modules ───────────────────────────────────────────────
    s10 = prs.slides.add_slide(blank)
    add_chrome(s10, "Major Implemented Modules", "14 cohesive backend & frontend modules spanning conversational, RAG, media, and coding workflows", 10)
    mods = [
        ("Auth, Quotas & Account Lifecycle", ["PyJWT login, SMTP reset, ZIP export", "Audited DELETE /api/v1/auth/me", "Atomic daily per-user usage quotas"], SAKURA),
        ("Conversational AI & Memory", ["SSE streaming across 4 LLM adapters", "Pin, archive, search, share links", "Long-term user memory extraction"], BLUE),
        ("Library & Hybrid RAG", ["Bearer-only downloads & Blob previews", "pdfplumber parsing + pgvector + BM25", "HTTP 202 async outbox storage purge"], TEAL),
        ("Multimodal Image & Audio", ["Intent-routed Pollinations raster jobs", "Idempotent variation batches (409 guard)", "Whisper STT upload (25 MB cap)"], AMBER),
        ("Durable Tasks & Cron Scheduler", ["4 standalone lease-fenced workers", "IANA timezone cron + unique runs", "Blocks forged internal task types (400)"], GREEN),
        ("Sakura Code & Projects", ["21-tool repository coding agent", "Live SSE diff & tool event replay", "Projects + verified GitHub integration"], SAKURA),
    ]
    for (x, y), (t, b, c) in zip(positions, mods):
        add_card(s10, x, y, 3.85, 2.55, t, b, accent=c, body_size=14)
    add_notes(s10, "Briefly summarize how the 14 modules fit together into six user-facing pillars without overwhelming the slide.")

    # ── Slide 11: AI & Hybrid RAG Workflow ────────────────────────────────────
    s11 = prs.slides.add_slide(blank)
    add_chrome(s11, "AI Routing & Hybrid RAG Workflow", "Per-user semantic + lexical retrieval with honest BM25 fallback and fail-closed privacy", 11)
    pic11 = s11.shapes.add_picture(str(rag_png), Inches(0), Inches(1.36), height=Inches(5.55))
    pic11.left = int((prs.slide_width - pic11.width) / 2)
    add_notes(s11, "Explain why combining pgvector cosine distance and Okapi BM25 via RRF outperforms vector-only search, and explain how private_data mode fails closed if Ollama is unconfigured.")

    # ── Slide 12: Sakura Coding Engine & Sandbox ──────────────────────────────
    s12 = prs.slides.add_slide(blank)
    add_chrome(s12, "Sakura Coding Engine & Docker Sandbox", "Autonomous repository editing isolated behind an authenticated non-root Docker boundary", 12)
    pic12 = s12.shapes.add_picture(str(sandbox_png), Inches(0), Inches(1.36), height=Inches(5.55))
    pic12.left = int((prs.slide_width - pic12.width) / 2)
    add_notes(s12, "Stress the security boundary: neither FastAPI nor coding-worker touches docker.sock. Only sandbox-executor launches ephemeral UID 1001 containers with --network none and single-use HMAC capabilities.")

    # ── Slide 13: Security Architecture ───────────────────────────────────────
    s13 = prs.slides.add_slide(blank)
    add_chrome(s13, "Security Architecture", "Defense-in-depth controls verified by automated regression tests and live checks", 13)
    sec_cards = [
        ("Authentication & Zero URL Tokens", ["Migrated AuthManager to PyJWT (HS256); Passlib pbkdf2_sha256.", "Header-only Bearer file access (?token= rejected HTTP 401).", "Single-use 60-second WebSocket tickets prevent URL token leakage."], SAKURA),
        ("Tenant Isolation & Input Validation", ["Strict user_id ownership on all 32 tables (cross-user returns 404).", "Malformed UUIDs rejected (400); forged internal task types blocked (400).", "Path/symlink traversal containment inside coding workspaces."], BLUE),
        ("Fail-Closed Guards, Quotas & Rate Limits", ["Production startup refuses default, short (<32), or reused secrets.", "Redis auth rate limits fail closed (HTTP 503); CIDR-validated proxy IPs.", "Atomic daily quotas (chat 500, images 50, coding 50, uploads 100)."], TEAL),
        ("Container & Frontend Hardening", ["Non-root UID 1001, --network none, --cap-drop ALL, 2 CPU / 512 MB / 64 PIDs.", "Allowlisted child env vars strip all host credentials.", "Next.js images.unoptimized=true disables /_next/image (verified HTTP 404)."], AMBER),
    ]
    for (x, y), (t, b, c) in zip(coords, sec_cards):
        add_card(s13, x, y, 5.93, 2.55, t, b, accent=c, body_size=14.5)
    add_notes(s13, "Highlight concrete verified controls—especially PyJWT migration, header-only file downloads, fail-closed Redis rate limiting, and non-root container isolation.")

    # ── Slide 14: Implementation Screenshots ──────────────────────────────────
    s14 = prs.slides.add_slide(blank)
    add_chrome(s14, "Implementation Screenshots", "Actual live captures from the running Next.js (:3000) and FastAPI (:8000) application", 14)
    shots = [
        (SHOT_DIR / "01_landing.png", "Landing Page (http://localhost:3000/)", 0.6, 1.38),
        (SHOT_DIR / "02_login.png", "Authentication Screen (/login)", 6.85, 1.38),
        (SHOT_DIR / "03_chat_workspace.png", "Authenticated Chat Workspace (/chat)", 0.6, 4.28),
        (SHOT_DIR / "04_api_docs.png", "FastAPI OpenAPI Documentation (/docs)", 6.85, 4.28),
    ]
    for img_path, caption, x, y in shots:
        frame = s14.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(5.88), Inches(2.68))
        frame.adjustments[0] = 0.03
        frame.fill.solid()
        frame.fill.fore_color.rgb = WHITE
        frame.line.color.rgb = BORDER
        if img_path.exists():
            s14.shapes.add_picture(str(img_path), Inches(x + 0.12), Inches(y + 0.08), width=Inches(5.64), height=Inches(2.22))
        cap = s14.shapes.add_textbox(Inches(x + 0.1), Inches(y + 2.34), Inches(5.68), Inches(0.3))
        cp = cap.text_frame.paragraphs[0]
        cp.alignment = PP_ALIGN.CENTER
        cp.text = caption
        cp.font.name = FONT_FAMILY
        cp.font.size = Pt(12)
        cp.font.bold = True
        cp.font.color.rgb = SLATE_DARK
    add_notes(s14, "Point out that all four screenshots are genuine live renders from the actual running Sakura AI application, not static mockups.")

    # ── Slide 15: Testing & Verified Results ──────────────────────────────────
    s15 = prs.slides.add_slide(blank)
    add_chrome(s15, "Testing & Verified Results", "Evidence-based verification across local suites, live user journeys, and GitHub Actions CI", 15)
    # Top 4 KPI cards
    stats = [
        ("253 Passed", "Local Backend Tests\n(18 PG/Docker gated, 0 fail)", BLUE, BLUE_SOFT),
        ("37 / 37 Passed", "Live Local Full-Stack\nAPI & UI User Journeys", TEAL, TEAL_SOFT),
        ("4 / 4 CI Jobs", "GitHub Actions Run\n(46167864598 on 03e213d)", GREEN, GREEN_SOFT),
        ("0 Orphans", "Verified Sandbox Child\nContainers Post-Run", SAKURA, SAKURA_SOFT),
    ]
    for i, (num, lbl, col, bgc) in enumerate(stats):
        box = s15.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.6 + i * 3.1), Inches(1.42), Inches(2.85), Inches(1.38))
        box.adjustments[0] = 0.08
        box.fill.solid()
        box.fill.fore_color.rgb = bgc
        box.line.color.rgb = col
        box.line.width = Pt(1.5)
        tf = box.text_frame
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p1 = tf.paragraphs[0]
        p1.alignment = PP_ALIGN.CENTER
        p1.text = num
        p1.font.name = FONT_FAMILY
        p1.font.size = Pt(24)
        p1.font.bold = True
        p1.font.color.rgb = col
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        p2.text = lbl
        p2.font.name = FONT_FAMILY
        p2.font.size = Pt(12)
        p2.font.color.rgb = SLATE_DARK

    # Verification summary table
    trows = [
        ["Verification Suite", "Scope Tested", "Observed Result"],
        ["Backend & PG15 CI", "Alembic 11 revs, 32-table parity, pgvector(1536), SKIP LOCKED, backup/restore tamper check", "PASS (0 skips on PG15)"],
        ["Frontend Build CI", "tsc --noEmit, next lint (0 errors), next build (12 pages), Playwright landing smoke", "PASS (Docker built)"],
        ["Docker Sandbox E2E", "Real non-root UID 1001 execution, --network none, HMAC capability, 0 orphans", "PASS (CI Linux)"],
        ["Full-Stack Browser E2E", "PG15 + Redis + Executor + API + 3 Workers + Next.js + unmocked Playwright", "PASS (CI Linux)"],
    ]
    tsh = s15.shapes.add_table(len(trows), 3, Inches(0.6), Inches(3.05), Inches(12.133), Inches(3.75))
    t = tsh.table
    t.columns[0].width = Inches(2.6)
    t.columns[1].width = Inches(6.933)
    t.columns[2].width = Inches(2.6)
    for r_i, r in enumerate(trows):
        for c_i, val in enumerate(r):
            c = t.cell(r_i, c_i)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid()
            c.fill.fore_color.rgb = NAVY if r_i == 0 else (WHITE if r_i % 2 == 1 else RGBColor(241, 245, 249))
            p = c.text_frame.paragraphs[0]
            p.text = val
            p.font.name = FONT_FAMILY
            p.font.size = Pt(13.5)
            p.font.bold = (r_i == 0 or c_i == 2)
            p.font.color.rgb = WHITE if r_i == 0 else (GREEN if c_i == 2 else SLATE_DARK)
    add_notes(s15, "Present only verified results. Clearly note that Docker and PG15 E2E suites ran on Ubuntu GitHub Actions CI while local Windows ran SQLite + live 37/37 checks.")

    # ── Slide 16: Limitations ─────────────────────────────────────────────────
    s16 = prs.slides.add_slide(blank)
    add_chrome(s16, "Known Limitations (Transparent Assessment)", "Honest engineering boundaries documented in the repository", 16)
    add_card(s16, 0.6, 1.48, 5.93, 5.3, "Infrastructure & Framework Boundaries", [
        "No Externally Provisioned Staging Host Yet: TLS domain, managed PG15/Redis, S3 credentials, and SMTP relay must be provisioned externally before public launch.",
        "Next.js 14 -> 16 Upgrade Pending: /_next/image advisories are mitigated immediately via images.unoptimized: true; full React 19 + Next 16 upgrade is tracked as a dedicated PR.",
        "Local Windows Dev Parity: Full container sandbox and pgvector concurrency require Docker/PostgreSQL (verified in Linux CI)."
    ], accent=AMBER, body_size=14.5)
    add_card(s16, 6.8, 1.48, 5.93, 5.3, "Feature & Provider Boundaries", [
        "Prompt-Context Image Edits: Image variations regenerate via prompt lineage rather than pixel-mask inpainting (truthfully reported by /api/v1/capabilities).",
        "Partial Connector Coverage: GitHub integration is live; Google Drive, Notion, Slack, Jira, and Postgres honestly return HTTP 501.",
        "Optional OpenAI Dependency: Dense embeddings and Whisper audio require OPENAI_API_KEY (RAG honestly falls back to BM25 when unset).",
        "Draft Legal Pages: /privacy and /terms require legal review before commercial launch."
    ], accent=SAKURA, body_size=14.5)
    add_notes(s16, "Faculty and technical interviewers appreciate intellectual honesty. Show that every limitation is tracked intentionally and truthfully surfaced by the API.")

    # ── Slide 17: Future Enhancements ─────────────────────────────────────────
    s17 = prs.slides.add_slide(blank)
    add_chrome(s17, "Future Enhancements", "Realistic next phases from private staging to public multi-tenant scale", 17)
    roadmap = [
        ("Phase 3: Controlled Private Staging", ["Provision hardened separate sandbox-executor host, TLS/Nginx, managed PG15, Redis 7, S3, and SMTP.", "Execute live remote backup/restore and k6/Locust load drills."], BLUE),
        ("Framework & Supply-Chain Hardening", ["Complete Next.js 16 + React 19 migration and resolve remaining 10 ESLint warnings.", "Add automated pip-audit and npm audit gates to GitHub Actions CI."], SAKURA),
        ("RAG & Vector Scaling", ["Add local open-source embedding adapters for 100% air-gapped Hybrid RAG.", "Introduce pgvector HNSW indexes, PostgreSQL tsvector GIN, and cross-encoder reranking."], TEAL),
        ("Public Multi-Tenant Sandbox & Ops", ["Evaluate Firecracker / gVisor microVM runtime alongside hardened Docker.", "Export Prometheus metrics & OpenTelemetry traces correlated via X-Request-ID."], GREEN),
    ]
    for (x, y), (t, b, c) in zip(coords, roadmap):
        add_card(s17, x, y, 5.93, 2.55, t, b, accent=c, body_size=14.5)
    add_notes(s17, "Frame each enhancement as a logical continuation of the clean abstractions already built into the codebase.")

    # ── Slide 18: Conclusion ──────────────────────────────────────────────────
    s18 = prs.slides.add_slide(blank)
    add_chrome(s18, "Conclusion", "Key engineering achievements and academic/practical significance", 18)
    add_card(s18, 0.6, 1.5, 12.133, 5.15, "Summary of Technical Contributions", [
        "Delivered a complete, multi-tenant full-stack AI platform unifying conversational streaming, Hybrid RAG, multimodal media, durable scheduling, and autonomous repository coding.",
        "Solved hard backend engineering problems rarely addressed in student projects: 32-table Alembic schema governance, native pgvector(1536) + Okapi BM25 fusion, lease-fenced workers, outbox object deletion, and non-root Docker sandbox isolation.",
        "Verified end-to-end reliability honestly through 253 passing local backend tests, 37/37 live full-stack user journeys, and 4/4 green GitHub Actions CI pipelines (Run 46157049085).",
        "Established clear documentation, architecture diagrams, demo playbooks, and operational runbooks suitable for academic evaluation, technical interviews, and private staging rollout."
    ], accent=SAKURA, body_size=16)
    add_notes(s18, "Summarize cleanly and transition to Q&A and live demonstration.")

    # ── Slide 19: Q&A ─────────────────────────────────────────────────────────
    s19 = prs.slides.add_slide(blank)
    add_bg(s19, NAVY)
    band19 = s19.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.18))
    band19.fill.solid()
    band19.fill.fore_color.rgb = SAKURA
    band19.line.fill.background()

    qbox = s19.shapes.add_textbox(Inches(1.0), Inches(1.85), Inches(11.333), Inches(2.2))
    qtf = qbox.text_frame
    qp = qtf.paragraphs[0]
    qp.alignment = PP_ALIGN.CENTER
    qp.text = "Thank You"
    qp.font.name = FONT_FAMILY
    qp.font.size = Pt(54)
    qp.font.bold = True
    qp.font.color.rgb = WHITE

    qp2 = qtf.add_paragraph()
    qp2.alignment = PP_ALIGN.CENTER
    qp2.text = "Questions & Live Demonstration"
    qp2.font.name = FONT_FAMILY
    qp2.font.size = Pt(26)
    qp2.font.color.rgb = RGBColor(253, 164, 175)
    qp2.space_before = Pt(10)

    rbox = s19.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(2.2), Inches(4.55), Inches(8.933), Inches(1.7))
    rbox.adjustments[0] = 0.08
    rbox.fill.solid()
    rbox.fill.fore_color.rgb = SLATE_DARK
    rbox.line.color.rgb = RGBColor(71, 85, 105)
    rtf = rbox.text_frame
    rtf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for idx, line in enumerate([
        "GitHub Repository: https://github.com/Abhiram-C-Divakaran/Sakura-AI",
        "Academic Report & Diagrams: docs/academic/PROJECT_REPORT.md  |  docs/architecture/",
        "Live Demo Playbook & Viva Prep: docs/DEMO_PLAYBOOK.md  |  docs/interview/",
    ]):
        rp = rtf.paragraphs[0] if idx == 0 else rtf.add_paragraph()
        rp.alignment = PP_ALIGN.CENTER
        rp.text = line
        rp.font.name = FONT_FAMILY
        rp.font.size = Pt(14)
        rp.font.color.rgb = RGBColor(226, 232, 240)
        rp.space_after = Pt(6)
    add_notes(s19, "Thank the evaluation panel and invite questions or transition directly into the live demo using docs/DEMO_PLAYBOOK.md.")

    OUT_PPTX.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT_PPTX))
    print(f"Generated presentation: {OUT_PPTX} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    build_deck()
