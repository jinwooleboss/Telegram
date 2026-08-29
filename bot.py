#!/usr/bin/env python3
"""
Bot Telegram - Planning Anime avec support multi-plateformes
"""

import asyncio
import io
import json
import logging
import os
import random
import re
import tempfile
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(BASE_DIR, "fonts", "Poppins-Bold.ttf")
FONT_MEDIUM = os.path.join(BASE_DIR, "fonts", "Poppins-Medium.ttf")
LOGOS_DIR = os.path.join(BASE_DIR, "logos")
ALLOWED_USERS_FILE = os.path.join(BASE_DIR, "allowed_users.json")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "5825526159"))
except ValueError:
    ADMIN_ID = 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Couleurs
BG_COLOR = (30, 32, 38)
WHITE = (255, 255, 255)
BLUE_ACCENT = (77, 163, 255)
ORANGE = (240, 128, 24)
GREY_TEXT = (210, 210, 215)
W_BASE = 1728
PADDING_X = 60

PLATFORM_COLORS = {
    "VIKI": (77, 163, 255)
    "prime video": (135, 206, 235),
    "amazon prime": (255, 255, 255),
    "prime": (135, 206, 235),
    "crunchyroll": (240, 128, 24),
    "netflix": (0, 0, 0),
    "adn": (0, 120, 225),
    "disney+": (0, 0, 255),
    "disney plus": (0, 0, 255),
    "adkami": (0, 150, 199),
    "amazon": (255, 255, 255),
    "iqiyi": (0, 160, 0),
}

# États
(DATE, IMAGE_CHOICE, IMAGE_UPLOAD, PLATFORM, CUSTOM_PLATFORM, 
 PLATFORM_CONTINUE, NAME, EPISODE, HEURE, VERSION, AJOUTER_OU_FIN,
 EDIT_MENU, EDIT_REMOVE, EDIT_SELECT, EDIT_FIELD, EDIT_VALUE) = range(16)

# Claviers
MAIN_MENU = ReplyKeyboardMarkup([
    ["🗓️ Créer un planning"],
    ["🆔 Mon ID", "👥 Utilisateurs"],
    ["❌ Annuler"],
], resize_keyboard=True)

BACKGROUND_KEYBOARD = ReplyKeyboardMarkup([
    ["🖼️ Envoyer une image"],
    ["🔎 Chercher sur Nautiljon"],
    ["🚫 Aucune image"],
], resize_keyboard=True)

PLATFORM_KEYBOARD = ReplyKeyboardMarkup([
    ["Prime video", "Crunchyroll"],
    ["Netflix", "ADN"],
    ["IQIYI", "Disney"],
    ["Amazon","VIKI", "Autre plateforme"],
], resize_keyboard=True)

PLATFORM_CONTINUE_KEYBOARD = ReplyKeyboardMarkup([
    ["➕ Ajouter une plateforme"],
    ["✅ Pas d'autre plateforme"],
], resize_keyboard=True)

VERSION_KEYBOARD = ReplyKeyboardMarkup([
    ["VF", "VO"],
    ["Les deux", "VOSTANG"],
], resize_keyboard=True)

CONTINUER_KEYBOARD = ReplyKeyboardMarkup([
    ["➕ Ajouter un anime"],
    ["✅ Terminer et générer l'image"],
], resize_keyboard=True)

POST_GEN_KEYBOARD = ReplyKeyboardMarkup([
    ["➕ Ajouter un anime", "✏️ Modifier un anime"],
    ["➖ Supprimer un anime", "🖼️ Modifier le fond"],
    ["📅 Modifier la date", "🔁 Régénérer l'image"],
    ["🆕 Nouveau planning", "✅ Terminé"],
], resize_keyboard=True)

EDIT_FIELD_KEYBOARD = ReplyKeyboardMarkup([
    ["📝 Nom"],
    ["📺 Épisode", "🕐 Heure"],
    ["📡 Plateforme", "🎙️ Version"],
    ["↩️ Retour"],
], resize_keyboard=True)

# ========== OUTILS ==========

def _font(path, size):
    try:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()

def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), str(text), font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])

def fit_text(draw, text, font_path, max_width, start_size, min_size=18):
    size = start_size
    while size >= min_size:
        font = _font(font_path, size)
        width, _ = _text_size(draw, text, font)
        if width <= max_width:
            return font
        size -= 2
    return _font(font_path, min_size)

def normalize_platform(name):
    value = str(name).strip().lower().replace("_", " ")
    if value == "amazon prime":
        return "prime video"
    return value

def _platform_color(name):
    return PLATFORM_COLORS.get(normalize_platform(name), (90, 95, 105))

def _load_logo(platform_name, target_h):
    fname = str(platform_name).strip().lower().replace(" ", "_").replace("+", "plus")
    path = os.path.join(LOGOS_DIR, fname + ".png")
    if not os.path.isfile(path):
        return None
    try:
        img = Image.open(path).convert("RGBA")
        if img.height <= 0:
            return None
        ratio = target_h / img.height
        img = img.resize((max(1, int(img.width * ratio)), target_h), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None

def clean_title(title):
    title = " ".join(str(title).strip().split())
    return title.upper() or "ANIME"

def normalize_version(value):
    value = str(value).strip().upper()
    if value in ("LES DEUX", "VF + VO", "VF+VO"):
        return "LES DEUX"
    if value in ("VOSTFR", "VOST", "VO"):
        return "VO"
    return value

def get_version_label(version):
    version = normalize_version(version)
    if version == "LES DEUX":
        return "VF + VO"
    return version

def _load_allowed_users():
    if not os.path.isfile(ALLOWED_USERS_FILE):
        return set()
    try:
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {int(x) for x in data}
    except Exception:
        pass
    return set()

def _save_allowed_users(users):
    try:
        with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(users), f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def is_authorized(user_id):
    if ADMIN_ID == 0:
        return False
    if user_id == ADMIN_ID:
        return True
    return user_id in _load_allowed_users()

def _time_sort_key(value):
    text = str(value).strip().upper()
    if not text:
        return 24 * 60
    match = re.search(r"(\d{1,2})\s*[H:]\s*(\d{1,2})?", text)
    if not match:
        return 24 * 60 + 1
    try:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return 24 * 60 + 1
        return hour * 60 + minute
    except (ValueError, TypeError):
        return 24 * 60 + 1

def sort_entries_by_time(entries):
    return sorted(entries, key=lambda e: _time_sort_key(e.get("heure", "")))

def cleanup_background(context):
    path = context.user_data.get("background_path")
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    context.user_data["background_path"] = None

# ========== GÉNÉRATION IMAGE ==========

def generate_planning_image(date_str, entries, background_path=None):
    logger.info("GEN: début génération")
    if not entries:
        raise ValueError("Aucun anime à afficher.")
    
    entries = sort_entries_by_time(entries)
    W = W_BASE
    
    platform_entries = []
    vf_entries = []
    
    for entry in entries:
        version = normalize_version(entry.get("version", ""))
        if version in ("VO", "VOSTANG"):
            platform_entries.append(entry)
        elif version == "VF":
            vf_entries.append(entry)
        elif version == "LES DEUX":
            platform_entries.append(entry)
            vf_entries.append(entry)
    
    platforms_order = []
    by_platform = {}
    
    for entry in platform_entries:
        platforms_list = entry.get("platforms_list", [entry.get("platform", "Autre")])
        platform_key = " + ".join(sorted(platforms_list))
        if not platform_key:
            platform_key = "Autre"
        if platform_key not in by_platform:
            by_platform[platform_key] = []
            platforms_order.append(platform_key)
        by_platform[platform_key].append(entry)
    
    row_h = 72
    header_h = 330
    content_h = header_h
    
    for platform in platforms_order:
        content_h += 120
        content_h += len(by_platform[platform]) * row_h
        content_h += 40
    
    if vf_entries:
        content_h += 150
        content_h += len(vf_entries) * row_h
    
    content_h += 150
    H_ratio = round(W * 4 / 3)
    H = max(H_ratio, content_h)
    
    if content_h > H_ratio:
        W = round(H * 3 / 4)
    
    logger.info("GEN: canvas W=%s H=%s content_h=%s", W, H, content_h)
    
    content = Image.new("RGBA", (W, content_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(content)
    
    f_title = _font(FONT_BOLD, 64)
    f_subtitle = _font(FONT_BOLD, 40)
    f_badge = _font(FONT_BOLD, 26)
    f_row = _font(FONT_BOLD, 30)
    f_vf = _font(FONT_BOLD, 46)
    
    cy = 70
    
    # Titre
    draw.ellipse([PADDING_X, cy, PADDING_X + 46, cy + 46], fill=WHITE)
    draw.ellipse([PADDING_X + 10, cy + 10, PADDING_X + 36, cy + 36], fill=BG_COLOR)
    draw.text((PADDING_X + 70, cy - 8), "PLANNING", font=f_title, fill=WHITE)
    
    cy += 100
    
    prefix = "LES SORTIES ANIMES DU "
    draw.text((PADDING_X, cy), prefix, font=f_subtitle, fill=WHITE)
    prefix_w, _ = _text_size(draw, prefix, f_subtitle)
    
    date_font = fit_text(draw, str(date_str).upper(), FONT_BOLD, W - PADDING_X - prefix_w - 20, 40, 24)
    draw.text((PADDING_X + prefix_w + 10, cy), str(date_str).upper(), font=date_font, fill=BLUE_ACCENT)
    
    cy += 130
    
    # Plateformes
    for platform in platforms_order:
        platforms_list_for_display = platform.split(" + ")
        first_platform = platforms_list_for_display[0]
        color = _platform_color(first_platform)
        logo_h = 70
        
        draw.rectangle([0, cy, 14, cy + logo_h], fill=ORANGE)
        platform_text = platform.upper()
        tw, _ = _text_size(draw, platform_text, f_badge)
        badge_w = max(210, tw + 80)
        
        draw.rounded_rectangle([PADDING_X, cy, PADDING_X + badge_w, cy + logo_h], radius=12, fill=color)
        
        # Logos
        logos = []
        for plat in platforms_list_for_display:
            logo = _load_logo(plat, logo_h - 20)
            if logo:
                logos.append(logo)
        
        if logos:
            max_w = badge_w - 30
            total_w = sum(logo.width for logo in logos)
            
            if total_w > max_w:
                ratio = max_w / total_w
                logos = [logo.resize((max(1, int(logo.width * ratio)), max(1, int(logo.height * ratio))), Image.Resampling.LANCZOS) for logo in logos]
            
            total_w = sum(logo.width for logo in logos)
            start_x = PADDING_X + (badge_w - total_w) // 2
            current_x = start_x
            
            for logo in logos:
                content.paste(logo, (current_x, cy + (logo_h - logo.height) // 2), logo)
                current_x += logo.width + 5
        else:
            draw.text((PADDING_X + (badge_w - tw) // 2, cy + 17), platform_text, font=f_badge, fill=WHITE)
        
        cy += 100
        col_ep = int(W * 0.62)
        col_time = int(W * 0.84)
        
        for entry in by_platform[platform]:
            title = clean_title(entry.get("name", "ANIME"))
            title_font = fit_text(draw, title, FONT_BOLD, col_ep - PADDING_X - 40, 32, 18)
            draw.text((PADDING_X, cy), title, font=title_font, fill=WHITE)
            draw.text((col_ep, cy), "ÉPISODE " + str(entry.get("episode", "")), font=f_row, fill=WHITE)
            
            time_font = fit_text(draw, str(entry.get("heure", "")).upper(), FONT_BOLD, W - col_time - PADDING_X, 30, 18)
            draw.text((col_time, cy), str(entry.get("heure", "")).upper(), font=time_font, fill=BLUE_ACCENT)
            
            cy += row_h
        
        cy += 40
    
    # VF
    if vf_entries:
        tw, _ = _text_size(draw, "LES SORTIES VF", f_vf)
        badge_w = max(560, tw + 160)
        draw.rounded_rectangle([PADDING_X, cy, PADDING_X + badge_w, cy + 90], radius=24, fill=ORANGE)
        draw.text((PADDING_X + 110, cy + 20), "🇫🇷  LES SORTIES VF", font=f_vf, fill=WHITE)
        
        cy += 140
        col_name = PADDING_X + 65
        col_ep = int(W * 0.62)
        col_time = int(W * 0.84)
        
        for entry in vf_entries:
            color = _platform_color(entry.get("platform", ""))
            draw.rounded_rectangle([PADDING_X, cy + 6, PADDING_X + 44, cy + 50], radius=8, fill=color)
            
            initial = str(entry.get("platform", "?"))[:1].upper()
            iw, ih = _text_size(draw, initial, f_badge)
            draw.text((PADDING_X + (44 - iw) // 2, cy + 6 + (44 - ih) // 2 - 2), initial, font=f_badge, fill=WHITE)
            
            title = clean_title(entry.get("name", "ANIME"))
            title_font = fit_text(draw, title, FONT_BOLD, col_ep - col_name - 30, 32, 18)
            draw.text((col_name, cy), title, font=title_font, fill=WHITE)
            draw.text((col_ep, cy), "ÉPISODE " + str(entry.get("episode", "")), font=f_row, fill=WHITE)
            draw.text((col_time, cy), str(entry.get("heure", "")).upper(), font=f_row, fill=BLUE_ACCENT)
            
            cy += row_h
    
    # Fond
    if background_path and os.path.isfile(background_path):
        try:
            bg = Image.open(background_path).convert("RGB")
            bg.thumbnail((2500, 2500), Image.Resampling.LANCZOS)
            src_w, src_h = bg.size
            target_ratio = W / H
            src_ratio = src_w / src_h
            
            if src_ratio > target_ratio:
                new_w = int(src_h * target_ratio)
                left = (src_w - new_w) // 2
                bg = bg.crop((left, 0, left + new_w, src_h))
            else:
                new_h = int(src_w / target_ratio)
                top = (src_h - new_h) // 2
                bg = bg.crop((0, top, src_w, top + new_h))
            
            bg = bg.resize((W, H), Image.Resampling.LANCZOS)
            darken_factor = 1.0 - (160 / 255.0)
            bg = bg.point(lambda p: int(p * darken_factor))
            background = bg
        except Exception:
            background = Image.new("RGB", (W, H), BG_COLOR)
    else:
        background = Image.new("RGB", (W, H), BG_COLOR)
        side = ImageDraw.Draw(background)
        side.rectangle([0, 0, 260, H], fill=(38, 40, 47))
    
    offset_y = max(0, (H - content_h) // 2)
    background.paste(content, (0, offset_y), content)
    
    # Footer
    final_draw = ImageDraw.Draw(background)
    footer = "CONTACTE MOI @AkiraKuroda"
    f_footer = _font(FONT_BOLD, 22)
    fw, fh = _text_size(final_draw, footer, f_footer)
    final_draw.text(((W - fw) // 2, H - 70), footer, font=f_footer, fill=GREY_TEXT)
    
    buffer = io.BytesIO()
    background.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    
    logger.info("GEN: PNG créée : %d octets", len(buffer.getvalue()))
    return buffer

# ========== HANDLERS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Salut !\n\nJe suis ton générateur de planning anime.\n\nUtilise les boutons ci-dessous.",
        reply_markup=MAIN_MENU,
    )

async def cmd_id(update, context):
    await update.message.reply_text(
        f"🆔 Ton ID Telegram : {update.effective_user.id}",
        reply_markup=MAIN_MENU,
    )

async def cmd_utilisateurs(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Réservé à l'administrateur.")
        return
    users = _load_allowed_users()
    if not users:
        await update.message.reply_text(f"👑 Administrateur : {ADMIN_ID}\n\n👥 Aucun utilisateur autorisé.")
        return
    listing = "\n".join(f"• {user_id}" for user_id in sorted(users))
    await update.message.reply_text(f"👑 Administrateur : {ADMIN_ID}\n\n👥 Utilisateurs autorisés :\n\n{listing}")

async def createplanning(update, context):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Tu n'es pas autorisé à utiliser ce bot.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    
    cleanup_background(context)
    context.user_data.clear()
    context.user_data["entries"] = []
    context.user_data["background_path"] = None
    context.user_data["image_mode"] = None
    
    await update.message.reply_text("🗓️ Création d'un nouveau planning.\n\nQuelle est la date à afficher ?\n\nExemple :\nVendredi 21 Août", reply_markup=ReplyKeyboardRemove())
    return DATE

async def recevoir_date_edit(update, context):
    date = update.message.text.strip()
    if not date:
        await update.message.reply_text("❌ La date ne peut pas être vide.")
        return DATE
    
    if context.user_data.get("changing_date"):
        context.user_data["date"] = date
        context.user_data["changing_date"] = False
        await update.message.reply_text("✅ Date modifiée.\n\n🔄 Régénération de l'image...")
        await send_planning(update, context)
        return EDIT_MENU
    
    context.user_data["date"] = date
    await update.message.reply_text("🖼️ Que veux-tu faire pour l'image de fond ?\n\n🖼️ Envoyer une image\n🔎 Chercher sur Nautiljon\n🚫 Aucune image", reply_markup=BACKGROUND_KEYBOARD)
    return IMAGE_CHOICE

async def image_choice(update, context):
    choice = update.message.text.strip().lower()
    
    if "envoyer" in choice:
        context.user_data["image_mode"] = "upload"
        await update.message.reply_text("🖼️ Envoie maintenant l'image que tu veux utiliser comme fond.", reply_markup=ReplyKeyboardRemove())
        return IMAGE_UPLOAD
    
    if "nautiljon" in choice:
        context.user_data["image_mode"] = "nautiljon"
        if context.user_data.get("changing_background"):
            context.user_data["changing_background"] = False
            await update.message.reply_text("✅ Fond défini.\n🔄 Régénération de l'image...")
            await send_planning(update, context)
            return EDIT_MENU
        await update.message.reply_text("🔎 D'accord. Le bot cherchera automatiquement une affiche sur Nautiljon après les anime.", reply_markup=ReplyKeyboardRemove())
        return await ask_platform(update, context)
    
    if "aucune" in choice:
        context.user_data["image_mode"] = "none"
        cleanup_background(context)
        if context.user_data.get("changing_background"):
            context.user_data["changing_background"] = False
            await update.message.reply_text("🚫 Fond supprimé.\n🔄 Régénération de l'image...")
            await send_planning(update, context)
            return EDIT_MENU
        await update.message.reply_text("🚫 Aucun fond.", reply_markup=ReplyKeyboardRemove())
        return await ask_platform(update, context)
    
    await update.message.reply_text("❌ Choisis l'une des trois options.", reply_markup=BACKGROUND_KEYBOARD)
    return IMAGE_CHOICE

async def image_upload(update, context):
    if not update.message.photo:
        await update.message.reply_text("📷 Envoie une photo.")
        return IMAGE_UPLOAD
    
    try:
        photo = update.message.photo[-1]
        telegram_file = await photo.get_file()
        path = os.path.join(tempfile.gettempdir(), f"planning_bg_{update.effective_chat.id}_{random.randint(1000, 9999)}.jpg")
        await telegram_file.download_to_drive(path)
        
        old = context.user_data.get("background_path")
        if old and old != path and os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
        
        context.user_data["background_path"] = path
        context.user_data["image_mode"] = "upload"
        
        if context.user_data.get("changing_background"):
            context.user_data["changing_background"] = False
            await update.message.reply_text("✅ Nouveau fond enregistré !\n🔄 Régénération de l'image...")
            await send_planning(update, context)
            return EDIT_MENU
        
        await update.message.reply_text("✅ Image enregistrée !", reply_markup=ReplyKeyboardRemove())
        return await ask_platform(update, context)
    except Exception as exc:
        await update.message.reply_text(f"❌ Impossible d'enregistrer l'image.\n\n{type(exc).__name__}: {exc}")
        return IMAGE_UPLOAD

async def ask_platform(update, context):
    await update.message.reply_text("📡 Plateforme de diffusion ?", reply_markup=PLATFORM_KEYBOARD)
    return PLATFORM

async def recevoir_platform(update, context):
    platform = update.message.text.strip()
    
    if platform == "Autre plateforme":
        await update.message.reply_text("📡 Écris le nom de la plateforme.", reply_markup=ReplyKeyboardRemove())
        return CUSTOM_PLATFORM
    
    if "platforms" not in context.user_data.get("current", {}):
        context.user_data["current"] = {"platforms": []}
    
    context.user_data["current"]["platforms"].append(platform)
    nb_platforms = len(context.user_data["current"]["platforms"])
    
    await update.message.reply_text(
        f"✅ {platform} ajoutée.\n\nVeux-tu ajouter une autre plateforme ?\n(Maximum 3 au total, {nb_platforms} sélectionnée(s))",
        reply_markup=PLATFORM_CONTINUE_KEYBOARD,
    )
    return PLATFORM_CONTINUE

async def recevoir_custom_platform(update, context):
    platform = update.message.text.strip()
    
    if not platform:
        await update.message.reply_text("❌ Le nom ne peut pas être vide.")
        return CUSTOM_PLATFORM
    
    if "platforms" not in context.user_data.get("current", {}):
        context.user_data["current"] = {"platforms": []}
    
    context.user_data["current"]["platforms"].append(platform)
    nb_platforms = len(context.user_data["current"]["platforms"])
    
    await update.message.reply_text(
        f"✅ {platform} ajoutée.\n\nVeux-tu ajouter une autre plateforme ?\n(Maximum 3 au total, {nb_platforms} sélectionnée(s))",
        reply_markup=PLATFORM_CONTINUE_KEYBOARD,
    )
    return PLATFORM_CONTINUE

async def platform_continue(update, context):
    choice = update.message.text.strip().lower()
    platforms = context.user_data.get("current", {}).get("platforms", [])
    
    if "ajouter" in choice:
        if len(platforms) >= 3:
            await update.message.reply_text("⚠️ Maximum 3 plateformes atteint.", reply_markup=PLATFORM_KEYBOARD)
            return PLATFORM_CONTINUE
        await update.message.reply_text("📡 Plateforme supplémentaire ?", reply_markup=PLATFORM_KEYBOARD)
        return PLATFORM
    
    if "pas" in choice or "✅" in choice:
        if not platforms:
            await update.message.reply_text("❌ Au moins une plateforme requise.")
            return PLATFORM_CONTINUE
        await update.message.reply_text("📝 Nom de l'anime ?", reply_markup=ReplyKeyboardRemove())
        return NAME
    
    await update.message.reply_text("❌ Choisis une option.", reply_markup=PLATFORM_CONTINUE_KEYBOARD)
    return PLATFORM_CONTINUE

async def recevoir_name(update, context):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Le nom ne peut pas être vide.")
        return NAME
    context.user_data["current"]["name"] = name
    await update.message.reply_text("📺 Numéro de l'épisode ?")
    return EPISODE

async def recevoir_episode(update, context):
    episode = update.message.text.strip()
    if not episode:
        await update.message.reply_text("❌ Indique un numéro.")
        return EPISODE
    context.user_data["current"]["episode"] = episode
    await update.message.reply_text("🕐 Heure de diffusion ?\nExemple : 16H30")
    return HEURE

async def recevoir_heure(update, context):
    heure = update.message.text.strip()
    if not heure:
        await update.message.reply_text("❌ L'heure ne peut pas être vide.")
        return HEURE
    context.user_data["current"]["heure"] = heure
    await update.message.reply_text("🎙️ Version ?\n\nVF = uniquement sortie VF\nVO = sortie plateforme\nLes deux = VF + VO", reply_markup=VERSION_KEYBOARD)
    return VERSION

async def recevoir_version(update, context):
    value = normalize_version(update.message.text)
    
    if value not in {"VF", "VO", "VOSTANG", "LES DEUX"}:
        await update.message.reply_text("❌ Choisis une version avec les boutons.", reply_markup=VERSION_KEYBOARD)
        return VERSION
    
    current = context.user_data["current"]
    current["version"] = value
    
    entry_to_save = current.copy()
    entry_to_save["platforms_list"] = current.get("platforms", [])
    entry_to_save["platform"] = current.get("platforms", ["Autre"])[0]
    
    context.user_data["entries"].append(entry_to_save)
    recap = entry_to_save.copy()
    context.user_data["current"] = {}
    
    platforms_display = " + ".join(recap.get("platforms_list", [recap.get("platform", "Autre")]))
    
    await update.message.reply_text(
        f"✅ Anime ajouté !\n\n🎬 {recap['name']}\n📺 Épisode : {recap['episode']}\n🕐 Heure : {recap['heure']}\n📡 Plateforme(s) : {platforms_display}\n🎙️ Version : {get_version_label(recap['version'])}\n\nQue veux-tu faire ?",
        reply_markup=CONTINUER_KEYBOARD,
    )
    return AJOUTER_OU_FIN

async def ajouter_ou_fin(update, context):
    choice = update.message.text.strip().lower()
    
    if "ajouter" in choice:
        return await ask_platform(update, context)
    
    if "terminer" in choice or "générer" in choice or "generer" in choice:
        entries = context.user_data.get("entries", [])
        if not entries:
            await update.message.reply_text("❌ Aucun anime ajouté.")
            return AJOUTER_OU_FIN
        
        await update.message.reply_text("🖼️ Génération du planning...")
        await send_planning(update, context)
        return EDIT_MENU
    
    await update.message.reply_text("❌ Choisis une option.", reply_markup=CONTINUER_KEYBOARD)
    return AJOUTER_OU_FIN

async def _generate_and_send(bot, chat_id, date, entries, background_path):
    try:
        logger.info("================================")
        logger.info("GÉNÉRATION BACKGROUND - chat=%s", chat_id)
        logger.info("Date : %s", date)
        logger.info("Nombre d'anime : %d", len(entries))
        
        image = await asyncio.to_thread(generate_planning_image, date, entries, background_path)
        image.seek(0)
        
        await bot.send_photo(chat_id=chat_id, photo=image, caption=f"📌 Planning des sorties animes du {date}")
        await bot.send_message(chat_id=chat_id, text="Que veux-tu faire ensuite ?", reply_markup=POST_GEN_KEYBOARD)
        
        logger.info("Image envoyée pour chat=%s", chat_id)
        logger.info("================================")
    except Exception as exc:
        logger.exception("ERREUR GÉNÉRATION chat=%s", chat_id)
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ Erreur pendant la génération :\n\n{type(exc).__name__}: {exc}", reply_markup=POST_GEN_KEYBOARD)
        except Exception:
            logger.exception("Impossible d'envoyer l'erreur")

async def send_planning(update, context):
    date = context.user_data.get("date", "")
    entries = [entry.copy() for entry in context.user_data.get("entries", [])]
    background_path = context.user_data.get("background_path")
    chat_id = update.effective_chat.id
    
    task = asyncio.create_task(_generate_and_send(context.bot, chat_id, date, entries, background_path))
    tasks = context.application.bot_data.setdefault("generation_tasks", set())
    tasks.add(task)
    
    def _task_done(done_task):
        tasks.discard(done_task)
        try:
            done_task.exception()
        except asyncio.CancelledError:
            pass
    
    task.add_done_callback(_task_done)
    logger.info("Génération lancée en arrière-plan pour chat=%s", chat_id)

async def edit_menu(update, context):
    choice = update.message.text.strip().lower()
    
    if "ajouter" in choice:
        return await ask_platform(update, context)
    
    if "modifier un anime" in choice:
        entries = context.user_data.get("entries", [])
        if not entries:
            await update.message.reply_text("❌ Aucun anime.", reply_markup=POST_GEN_KEYBOARD)
            return EDIT_MENU
        listing = "\n".join(f"{i + 1}. {e['name']} (Ep. {e['episode']} — {e['heure']})" for i, e in enumerate(entries))
        await update.message.reply_text(f"✏️ Quel anime modifier ?\n\n{listing}\n\nTape le numéro.", reply_markup=ReplyKeyboardRemove())
        return EDIT_SELECT
    
    if "supprimer" in choice:
        entries = context.user_data.get("entries", [])
        if not entries:
            await update.message.reply_text("❌ Aucun anime.", reply_markup=POST_GEN_KEYBOARD)
            return EDIT_MENU
        listing = "\n".join(f"{i + 1}. {e['name']}" for i, e in enumerate(entries))
        await update.message.reply_text(f"➖ Quel anime supprimer ?\n\n{listing}\n\nTape le numéro.", reply_markup=ReplyKeyboardRemove())
        return EDIT_REMOVE
    
    if "modifier le fond" in choice:
        context.user_data["changing_background"] = True
        await update.message.reply_text("🖼️ Choisis le nouveau fond :", reply_markup=BACKGROUND_KEYBOARD)
        return IMAGE_CHOICE
    
    if "modifier la date" in choice:
        context.user_data["changing_date"] = True
        await update.message.reply_text("📅 Nouvelle date ?", reply_markup=ReplyKeyboardRemove())
        return DATE
    
    if "régénérer" in choice or "regenerer" in choice:
        await update.message.reply_text("🔄 Régénération de l'image...")
        await send_planning(update, context)
        return EDIT_MENU
    
    if "nouveau" in choice:
        cleanup_background(context)
        context.user_data.clear()
        context.user_data["entries"] = []
        await update.message.reply_text("🆕 Nouveau planning.\n\nQuelle est la date ?", reply_markup=ReplyKeyboardRemove())
        return DATE
    
    if "terminé" in choice or "termine" in choice:
        cleanup_background(context)
        context.user_data.clear()
        await update.message.reply_text("👍 Planning terminé !", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    
    await update.message.reply_text("❌ Choisis une option.", reply_markup=POST_GEN_KEYBOARD)
    return EDIT_MENU

async def edit_remove(update, context):
    entries = context.user_data.get("entries", [])
    text = update.message.text.strip()
    
    if not text.isdigit() or not (1 <= int(text) <= len(entries)):
        await update.message.reply_text(f"❌ Choisis un numéro entre 1 et {len(entries)}.")
        return EDIT_REMOVE
    
    index = int(text) - 1
    removed = entries.pop(index)
    await update.message.reply_text(f"🗑️ Anime supprimé : {removed['name']}\n\nUtilise 🔄 Régénérer l'image pour mettre à jour le planning.", reply_markup=POST_GEN_KEYBOARD)
    return EDIT_MENU

async def edit_select(update, context):
    entries = context.user_data.get("entries", [])
    text = update.message.text.strip()
    
    if not text.isdigit() or not (1 <= int(text) <= len(entries)):
        await update.message.reply_text(f"❌ Choisis un numéro entre 1 et {len(entries)}.")
        return EDIT_SELECT
    
    index = int(text) - 1
    context.user_data["edit_index"] = index
    anime = entries[index]
    
    platforms_display = " + ".join(anime.get("platforms_list", [anime.get("platform", "Autre")]))
    
    await update.message.reply_text(
        f"✏️ Anime sélectionné :\n\n🎬 {anime['name']}\n📺 Épisode : {anime['episode']}\n🕐 Heure : {anime['heure']}\n📡 Plateforme(s) : {platforms_display}\n🎙️ Version : {get_version_label(anime['version'])}\n\nQue veux-tu modifier ?",
        reply_markup=EDIT_FIELD_KEYBOARD,
    )
    return EDIT_FIELD

async def edit_field(update, context):
    choice = update.message.text.strip().lower()
    
    if "retour" in choice:
        await update.message.reply_text("↩️ Retour.", reply_markup=POST_GEN_KEYBOARD)
        return EDIT_MENU
    
    mapping = {"nom": "name", "épisode": "episode", "heure": "heure", "plateforme": "platform", "version": "version"}
    field = None
    
    for key, value in mapping.items():
        if key in choice:
            field = value
            break
    
    if field is None:
        await update.message.reply_text("❌ Choisis un champ.", reply_markup=EDIT_FIELD_KEYBOARD)
        return EDIT_FIELD
    
    context.user_data["edit_field"] = field
    context.user_data["editing_custom_platform"] = False
    
    if field == "version":
        await update.message.reply_text("🎙️ Nouvelle version ?", reply_markup=VERSION_KEYBOARD)
        return EDIT_VALUE
    
    if field == "platform":
        await update.message.reply_text("📡 Nouvelle plateforme ?", reply_markup=PLATFORM_KEYBOARD)
        return EDIT_VALUE
    
    prompts = {"name": "📝 Nouveau nom ?", "episode": "📺 Nouvel épisode ?", "heure": "🕐 Nouvelle heure ?"}
    await update.message.reply_text(prompts[field], reply_markup=ReplyKeyboardRemove())
    return EDIT_VALUE

async def edit_value(update, context):
    entries = context.user_data.get("entries", [])
    index = context.user_data.get("edit_index")
    field = context.user_data.get("edit_field")
    
    if index is None or field is None or index < 0 or index >= len(entries):
        await update.message.reply_text("❌ Erreur de modification.", reply_markup=POST_GEN_KEYBOARD)
        return EDIT_MENU
    
    value = update.message.text.strip()
    
    if field == "platform":
        if value == "Autre plateforme" and not context.user_data.get("editing_custom_platform"):
            context.user_data["editing_custom_platform"] = True
            await update.message.reply_text("📡 Écris le nom de la plateforme.", reply_markup=ReplyKeyboardRemove())
            return EDIT_VALUE
        if not value:
            await update.message.reply_text("❌ Le nom de la plateforme ne peut pas être vide.")
            return EDIT_VALUE
        context.user_data["editing_custom_platform"] = False
    elif field == "version":
        value = normalize_version(value)
        if value not in {"VF", "VO", "VOSTANG", "LES DEUX"}:
            await update.message.reply_text("❌ Version invalide.", reply_markup=VERSION_KEYBOARD)
            return EDIT_VALUE
    elif field == "name":
        if not value:
            await update.message.reply_text("❌ Le nom ne peut pas être vide.")
            return EDIT_VALUE
    elif field == "episode":
        if not value:
            await update.message.reply_text("❌ L'épisode ne peut pas être vide.")
            return EDIT_VALUE
    elif field == "heure":
        if not value:
            await update.message.reply_text("❌ L'heure ne peut pas être vide.")
            return EDIT_VALUE
    
    entries[index][field] = value
    context.user_data.pop("edit_field", None)
    context.user_data.pop("edit_index", None)
    context.user_data.pop("editing_custom_platform", None)
    
    await update.message.reply_text("✅ Modification enregistrée !\n\n🔄 Choisis « Régénérer l'image » pour actualiser le planning.", reply_markup=POST_GEN_KEYBOARD)
    return EDIT_MENU

async def annuler(update, context):
    cleanup_background(context)
    context.user_data.clear()
    await update.message.reply_text("❌ Création annulée.", reply_markup=MAIN_MENU)
    return ConversationHandler.END

async def error_handler(update, context):
    logger.error("Erreur Telegram : %s", context.error, exc_info=context.error)

# ========== MAIN ==========

def main():
    if not TOKEN:
        raise RuntimeError("❌ TOKEN TELEGRAM MANQUANT.\n\nDéfinis la variable :\nTELEGRAM_BOT_TOKEN")
    
    if ADMIN_ID == 0:
        raise RuntimeError("❌ ADMIN_ID MANQUANT.")
    
    application = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("createplanning", createplanning),
            MessageHandler(filters.Regex(r"^🗓️ Créer un planning$"), createplanning),
        ],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_date_edit)],
            IMAGE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, image_choice)],
            IMAGE_UPLOAD: [MessageHandler(filters.PHOTO, image_upload)],
            PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_platform)],
            CUSTOM_PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_custom_platform)],
            PLATFORM_CONTINUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, platform_continue)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_name)],
            EPISODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_episode)],
            HEURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_heure)],
            VERSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_version)],
            AJOUTER_OU_FIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ajouter_ou_fin)],
            EDIT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_menu)],
            EDIT_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_remove)],
            EDIT_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_select)],
            EDIT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field)],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
        },
        fallbacks=[
            CommandHandler("cancel", annuler),
            MessageHandler(filters.Regex(r"^❌ Annuler$"), annuler),
        ],
        allow_reentry=True,
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("utilisateurs", cmd_utilisateurs))
    application.add_handler(MessageHandler(filters.Regex(r"^🆔 Mon ID$"), cmd_id))
    application.add_handler(MessageHandler(filters.Regex(r"^👥 Utilisateurs$"), cmd_utilisateurs))
    application.add_handler(MessageHandler(filters.Regex(r"^❌ Annuler$"), annuler))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    logger.info("================================")
    logger.info("BOT DÉMARRÉ")
    logger.info("ADMIN_ID = %s", ADMIN_ID)
    logger.info("BASE_DIR = %s", BASE_DIR)
    logger.info("================================")
    
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()