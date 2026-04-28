import os
import io
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, Arc
from matplotlib.animation import FuncAnimation
from matplotlib.lines import Line2D
from scipy.ndimage import gaussian_filter
from PIL import Image as PILImage, ImageDraw, ImageFont

LABELS = [
    "PASS", "HEADER", "HIGH PASS", "OUT", "CROSS",
    "THROW IN", "SHOT", "PLAYER SUCCESSFUL TACKLE", "FREE KICK", "GOAL"
]

# pitch colors
LIGHT_GREEN = "#6da942"
DARK_GREEN = "#507d2a"
HOME_COLOR = "#CC0000"
AWAY_COLOR = "#0066CC"
BALL_COLOR = "purple"

# pitch dimensions
PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0


# ---------------------------------------------------------------------------
# format detection
# ---------------------------------------------------------------------------

def detect_format(df):
    """Auto-detect whether clip is PFF, FIFA raw, or PFF-compatible format.
    Returns 'pff', 'fifa_raw', or 'pff_compatible'.
    """
    cols = set(df.columns)
    if "home_centroids" in cols and "ball_x" in cols:
        return "fifa_raw"
    elif "homePlayers" in cols and "balls" in cols:
        return "pff"
    else:
        raise ValueError(f"Unknown clip format. Columns: {list(df.columns)}")


# ---------------------------------------------------------------------------
# pitch drawing
# ---------------------------------------------------------------------------

def draw_pitch(ax, length=105.0, width=68.0):
    """draw a soccer pitch on the given axes."""
    padding = 2.0

    bg = Rectangle((-padding, -padding), length + 2 * padding, width + 2 * padding,
                   color=LIGHT_GREEN, zorder=0)
    ax.add_patch(bg)

    num_stripes = 20
    sw = length / num_stripes
    for i in range(num_stripes):
        color = LIGHT_GREEN if i % 2 == 0 else DARK_GREEN
        stripe = Rectangle((i * sw, 0), sw, width, color=color, zorder=0)
        ax.add_patch(stripe)

    np.random.seed(42)
    noise = gaussian_filter(np.random.rand(200, 200), sigma=0.5)
    ax.imshow(noise, extent=(0, length, 0, width), alpha=0.03, zorder=1, cmap='gray')

    lc = 'white'
    lw = 2

    ax.plot([0, 0, length, length, 0], [0, width, width, 0, 0], color=lc, linewidth=lw)
    ax.plot([length / 2, length / 2], [0, width], color=lc, linewidth=lw)
    ax.add_patch(Circle((length / 2, width / 2), 9.15, color=lc, fill=False, linewidth=lw))
    ax.plot(length / 2, width / 2, 'o', color=lc, markersize=5)

    for x_start in [0, length - 16.5]:
        ax.add_patch(Rectangle((x_start, width / 2 - 20.15), 16.5, 40.3,
                               edgecolor=lc, fill=False, linewidth=lw))
    for x_start in [0, length - 5.5]:
        ax.add_patch(Rectangle((x_start, width / 2 - 8.5), 5.5, 17,
                               edgecolor=lc, fill=False, linewidth=lw))

    ax.add_patch(Arc((11, width / 2), 18.3, 18.3, theta1=308, theta2=52, color=lc, linewidth=lw))
    ax.add_patch(Arc((length - 11, width / 2), 18.3, 18.3, theta1=127, theta2=233, color=lc, linewidth=lw))
    ax.plot(11, width / 2, 'o', color=lc, markersize=5)
    ax.plot(length - 11, width / 2, 'o', color=lc, markersize=5)
    ax.plot([0, 0], [width / 2 - 3.66, width / 2 + 3.66], color=lc, linewidth=lw + 2)
    ax.plot([length, length], [width / 2 - 3.66, width / 2 + 3.66], color=lc, linewidth=lw + 2)

    for x, y, t1, t2 in [(0, 0, 0, 90), (0, width, 270, 360),
                          (length, 0, 90, 180), (length, width, 180, 270)]:
        ax.add_patch(Arc((x, y), 1.8, 1.8, theta1=t1, theta2=t2, color=lc, linewidth=lw))

    ax.set_xlim(-padding, length + padding)
    ax.set_ylim(-padding, width + padding)
    ax.set_aspect('equal')
    ax.axis('off')


# ---------------------------------------------------------------------------
# unified parsing (handles both PFF and FIFA formats)
# ---------------------------------------------------------------------------

def parse_players_pff(json_str):
    """Parse PFF/PFF-compatible homePlayers/awayPlayers JSON."""
    try:
        players = json.loads(json_str) if isinstance(json_str, str) else json_str
        if not isinstance(players, list):
            return []
        return [p for p in players if isinstance(p, dict)
                and p.get('x') is not None and p.get('y') is not None]
    except:
        return []


def parse_players_fifa(json_str, skip_roles=None):
    """Parse FIFA home_centroids/away_centroids JSON.
    Returns list of dicts normalized to PFF key names.
    """
    if skip_roles is None:
        skip_roles = {"Referee", "AssistantReferee1", "AssistantReferee2", "Unknown"}
    try:
        players = json.loads(json_str) if isinstance(json_str, str) else json_str
        if not isinstance(players, list):
            return []
        result = []
        for p in players:
            if not isinstance(p, dict):
                continue
            x = p.get('x')
            y = p.get('y')
            if x is None or y is None:
                continue
            jersey = str(p.get('jersey_number', ''))
            if jersey in ('-1', '', 'nan', 'None'):
                continue
            role = p.get('role_name', '')
            if role in skip_roles:
                continue
            result.append({
                'x': float(x),
                'y': float(y),
                'jerseyNum': jersey,
                'role_name': role,
            })
        return result
    except:
        return []


def parse_ball_pff(json_str):
    """Parse PFF balls JSON."""
    try:
        balls = json.loads(json_str) if isinstance(json_str, str) else json_str
        if isinstance(balls, dict) and balls.get('x') is not None:
            return balls
        if isinstance(balls, list):
            for b in balls:
                if isinstance(b, dict) and b.get('x') is not None:
                    return b
        return None
    except:
        return None


def parse_ball_fifa(row):
    """Parse FIFA ball from separate columns."""
    bx = row.get('ball_x', np.nan)
    by = row.get('ball_y', np.nan)
    if isinstance(bx, float) and np.isnan(bx):
        return None
    return {'x': float(bx), 'y': float(by), 'z': float(row.get('ball_z', 0.0))}


def get_frame_data(row, fmt):
    """Extract home_players, away_players, ball from a row, regardless of format.
    All coordinates are raw (centered origin).
    """
    if fmt == "pff":
        home = parse_players_pff(row.get('homePlayers', '[]'))
        away = parse_players_pff(row.get('awayPlayers', '[]'))
        ball = parse_ball_pff(row.get('balls', '[]'))
    elif fmt == "fifa_raw":
        home = parse_players_fifa(row.get('home_centroids', '[]'))
        away = parse_players_fifa(row.get('away_centroids', '[]'))
        ball = parse_ball_fifa(row)
    else:
        raise ValueError(f"Unknown format: {fmt}")

    return home, away, ball


# ---------------------------------------------------------------------------
# tracking frame rendering
# ---------------------------------------------------------------------------

def draw_tracking_frame(ax, row, fmt="pff", title=None):
    """draw a single tracking frame on the pitch axes."""
    draw_pitch(ax)

    home_players, away_players, ball = get_frame_data(row, fmt)

    # offset from centered coords to pitch coords (0 to 105, 0 to 68)
    x_off = PITCH_LENGTH / 2.0  # 52.5
    y_off = PITCH_WIDTH / 2.0   # 34.0

    for p in home_players:
        px = p['x'] + x_off
        py = p['y'] + y_off
        # clamp to pitch bounds for visualization
        px = np.clip(px, -1, PITCH_LENGTH + 1)
        py = np.clip(py, -1, PITCH_WIDTH + 1)
        ax.add_patch(Circle((px, py), 1.0, facecolor=HOME_COLOR,
                            edgecolor='black', linewidth=0.5, zorder=4))
        jersey = p.get('jerseyNum', '')
        if jersey:
            try:
                jersey_str = str(int(float(jersey)))
            except (ValueError, TypeError):
                jersey_str = str(jersey)
            ax.text(px, py, jersey_str, color='white', ha='center', va='center',
                    fontsize=7, fontweight='bold', zorder=5)

    for p in away_players:
        px = p['x'] + x_off
        py = p['y'] + y_off
        px = np.clip(px, -1, PITCH_LENGTH + 1)
        py = np.clip(py, -1, PITCH_WIDTH + 1)
        ax.add_patch(Circle((px, py), 1.0, facecolor=AWAY_COLOR,
                            edgecolor='black', linewidth=0.5, zorder=4))
        jersey = p.get('jerseyNum', '')
        if jersey:
            try:
                jersey_str = str(int(float(jersey)))
            except (ValueError, TypeError):
                jersey_str = str(jersey)
            ax.text(px, py, jersey_str, color='white', ha='center', va='center',
                    fontsize=7, fontweight='bold', zorder=5)

    if ball:
        bx = ball['x'] + x_off
        by = ball['y'] + y_off
        bx = np.clip(bx, -1, PITCH_LENGTH + 1)
        by = np.clip(by, -1, PITCH_WIDTH + 1)
        ax.add_patch(Circle((bx, by), 0.6, facecolor=BALL_COLOR,
                            edgecolor='black', linewidth=0.5, zorder=6))

    if title:
        ax.set_title(title, fontsize=11, fontweight='bold', color='white',
                     bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))


# ---------------------------------------------------------------------------
# main logic
# ---------------------------------------------------------------------------

def find_clip(annotations, label, index):
    """find a clip by label and occurrence index."""
    count = 0
    for entry in annotations['data']:
        if entry['labels']['action']['label'] == label:
            if count == index:
                return entry
            count += 1
    return None


def load_tracking_clip(tracking_dir, split, clip_path):
    """load a tracking parquet clip."""
    filename = os.path.basename(clip_path)
    full_path = os.path.join(tracking_dir, split, filename)
    if not os.path.exists(full_path):
        full_path = os.path.join(tracking_dir, clip_path)
    return pd.read_parquet(full_path)


def load_video_clip(video_dir, split, clip_path):
    """load a video npy clip."""
    filename = os.path.basename(clip_path)
    full_path = os.path.join(video_dir, split, filename)
    if not os.path.exists(full_path):
        full_path = os.path.join(video_dir, clip_path)
    return np.load(full_path)


def fig_to_pil(fig):
    """render a matplotlib figure to a PIL image."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.02)
    buf.seek(0)
    img = PILImage.open(buf).convert('RGB')
    plt.close(fig)
    return img


def render_tracking_to_pil(row, fmt="pff", target_width=600, title=None):
    """render a single tracking frame to a PIL image."""
    fig, ax = plt.subplots(figsize=(10, 7.5), dpi=120)
    draw_tracking_frame(ax, row, fmt=fmt, title=title)
    img = fig_to_pil(fig)
    w, h = img.size
    target_height = int(target_width * h / w)
    return img.resize((target_width, target_height), PILImage.LANCZOS)


def save_side_by_side_frames(tracking_df, video_frames, label, game_time, output_path,
                              fmt="pff", frame_indices=None):
    """save selected frames as a stitched image."""
    n_frames = len(tracking_df)

    if frame_indices is None:
        frame_indices = np.linspace(0, n_frames - 1, 4, dtype=int)

    n = len(frame_indices)
    cell_w = 500

    t_imgs = []
    for fi in frame_indices:
        img = render_tracking_to_pil(tracking_df.iloc[fi], fmt=fmt, target_width=cell_w)
        t_imgs.append(img)

    # video frames (if available)
    v_imgs = []
    has_video = video_frames is not None
    if has_video:
        for fi in frame_indices:
            img = PILImage.fromarray(video_frames[fi])
            target_h = int(cell_w * 0.56)
            img = img.resize((cell_w, target_h), PILImage.LANCZOS)
            v_imgs.append(img)

    t_cell_h = t_imgs[0].size[1]
    v_cell_h = v_imgs[0].size[1] if v_imgs else 0

    gap = 3
    label_w = 90
    title_h = 50

    total_w = label_w + n * cell_w + (n - 1) * gap
    if has_video:
        total_h = title_h + v_cell_h + gap + t_cell_h
    else:
        total_h = title_h + t_cell_h

    canvas = PILImage.new('RGB', (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
        font_frame = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except:
        font_title = ImageFont.load_default()
        font_label = font_title
        font_frame = font_title

    title_text = f"{label} at {game_time}"
    bbox = draw.textbbox((0, 0), title_text, font=font_title)
    tw = bbox[2] - bbox[0]
    draw.text(((total_w - tw) // 2, 20), title_text, fill=(0, 0, 0), font=font_title)

    if has_video:
        y_video = title_h
        for col, img in enumerate(v_imgs):
            x = label_w + col * (cell_w + gap)
            canvas.paste(img, (x, y_video))

        y_track = title_h + v_cell_h + gap
        for col, img in enumerate(t_imgs):
            x = label_w + col * (cell_w + gap)
            canvas.paste(img, (x, y_track))

        # row labels
        for text, y_center in [("Video", y_video + v_cell_h // 2),
                                ("Tracking", y_track + t_cell_h // 2)]:
            txt_img = PILImage.new('RGB', (300, 40), (255, 255, 255))
            txt_draw = ImageDraw.Draw(txt_img)
            txt_draw.text((0, 0), text, fill=(0, 0, 0), font=font_label)
            txt_bbox = txt_img.getbbox()
            if txt_bbox:
                txt_img = txt_img.crop(txt_bbox)
            txt_img = txt_img.rotate(90, expand=True)
            paste_x = label_w - txt_img.size[0] + 1
            paste_y = y_center - txt_img.size[1] // 2 - 80
            canvas.paste(txt_img, (paste_x, paste_y))
    else:
        y_track = title_h
        for col, img in enumerate(t_imgs):
            x = label_w + col * (cell_w + gap)
            canvas.paste(img, (x, y_track))

        # single row label
        txt_img = PILImage.new('RGB', (300, 40), (255, 255, 255))
        txt_draw = ImageDraw.Draw(txt_img)
        txt_draw.text((0, 0), "Tracking", fill=(0, 0, 0), font=font_label)
        txt_bbox = txt_img.getbbox()
        if txt_bbox:
            txt_img = txt_img.crop(txt_bbox)
        txt_img = txt_img.rotate(90, expand=True)
        paste_x = label_w - txt_img.size[0] + 1
        paste_y = y_track + t_cell_h // 2 - txt_img.size[1] // 2 - 80
        canvas.paste(txt_img, (paste_x, paste_y))

    # frame labels
    for col, fi in enumerate(frame_indices):
        x_base = label_w + col * (cell_w + gap)
        frame_text = f"t = {fi}"
        text_bbox_r = draw.textbbox((0, 0), frame_text, font=font_frame)
        text_h = text_bbox_r[3] - text_bbox_r[1]
        pad_y = 3

        pill_x = x_base + 20
        pill_y = y_track + t_cell_h - text_h - 2 * pad_y - 20
        draw.text((pill_x, pill_y), frame_text, fill=(255, 255, 0), font=font_frame)

        if has_video:
            pill_y_v = title_h + v_cell_h - text_h - 2 * pad_y - 20
            draw.text((x_base + 20, pill_y_v), frame_text,
                      fill=(255, 255, 0), font=font_frame)

    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)

    canvas.save(output_path, dpi=(200, 200))
    print(f"saved: {output_path}")


def save_side_by_side_gif(tracking_df, video_frames, label, game_time, output_path,
                           fmt="pff", fps=3):
    """save a gif with tracking (and optionally video)."""
    n_frames = len(tracking_df)
    has_video = video_frames is not None

    if has_video:
        fig, (ax_t, ax_v) = plt.subplots(1, 2, figsize=(14, 5))
    else:
        fig, ax_t = plt.subplots(1, 1, figsize=(10, 7))

    fig.suptitle(f"{label} at {game_time}", fontsize=14, fontweight='bold')

    def update(fi):
        ax_t.clear()
        draw_tracking_frame(ax_t, tracking_df.iloc[fi], fmt=fmt)
        ax_t.set_title("tracking", fontsize=11, fontweight='bold')
        ax_t.text(0.02, 0.02, f"frame {fi}/{n_frames - 1}", transform=ax_t.transAxes,
                  fontsize=8, color='white', verticalalignment='bottom',
                  bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))

        if has_video:
            ax_v.clear()
            ax_v.imshow(video_frames[fi])
            ax_v.axis('off')
            ax_v.set_title("video", fontsize=11, fontweight='bold')
            ax_v.text(0.02, 0.02, f"frame {fi}/{n_frames - 1}", transform=ax_v.transAxes,
                      fontsize=8, color='white', verticalalignment='bottom',
                      bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))

        return []

    anim = FuncAnimation(fig, update, frames=range(n_frames), blit=False, interval=1000 // fps)
    anim.save(output_path, writer='pillow', fps=fps, dpi=150)
    plt.close(fig)
    print(f"saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="visualize tracking events (PFF or FIFA)")
    parser.add_argument('--tracking-dir', required=True,
                        help='tracking dataset directory (PFF, FIFA raw, or PFF-compatible)')
    parser.add_argument('--video-dir', default=None,
                        help='video dataset directory (optional, for side-by-side)')
    parser.add_argument('--split', default='test')
    parser.add_argument('--label', default='GOAL')
    parser.add_argument('--index', type=int, default=0, help='occurrence index for the label')
    parser.add_argument('--output', default=None, help='output path (auto-generated if not set)')
    parser.add_argument('--gif', action='store_true', help='save as gif instead of static figure')
    parser.add_argument('--fps', type=int, default=3, help='fps for gif')
    parser.add_argument('--frames', type=int, nargs='+', default=None,
                        help='specific frame indices to show (for static figure)')
    args = parser.parse_args()

    # load tracking annotations
    t_ann_path = os.path.join(args.tracking_dir, f"annotations_{args.split}.json")
    with open(t_ann_path) as f:
        t_ann = json.load(f)

    # find the clip
    t_clip_entry = find_clip(t_ann, args.label, args.index)
    if not t_clip_entry:
        print(f"could not find {args.label} at index {args.index} in {args.split}")
        return

    t_meta = t_clip_entry['metadata']
    print(f"tracking: game={t_meta['game_id']} time={t_meta['game_time']} "
          f"pos={t_meta['position_ms']}ms")

    # load tracking clip and detect format
    t_input = t_clip_entry['inputs'][0]
    tracking_df = load_tracking_clip(args.tracking_dir, args.split, t_input['path'])
    fmt = detect_format(tracking_df)
    print(f"detected format: {fmt}")
    print(f"tracking clip: {len(tracking_df)} frames, columns: {list(tracking_df.columns)}")

    # optionally load video
    video_frames = None
    if args.video_dir:
        v_ann_path = os.path.join(args.video_dir, f"annotations_{args.split}.json")
        with open(v_ann_path) as f:
            v_ann = json.load(f)
        v_clip_entry = find_clip(v_ann, args.label, args.index)
        if v_clip_entry:
            v_input = v_clip_entry['inputs'][0]
            video_frames = load_video_clip(args.video_dir, args.split, v_input['path'])
            print(f"video clip: {video_frames.shape}")
        else:
            print("warning: could not find matching video clip, showing tracking only")

    # generate output path
    label_clean = args.label.replace(' ', '_')
    game_time = t_meta['game_time'].replace(' ', '').replace('-', '_').replace(':', '')

    if args.output:
        output_path = args.output
    else:
        ext = 'gif' if args.gif else 'png'
        source = "fifa" if fmt == "fifa_raw" else "pff"
        output_path = f"viz_{source}_{label_clean}_{game_time}_{args.split}.{ext}"

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    if args.gif:
        save_side_by_side_gif(tracking_df, video_frames, args.label, t_meta['game_time'],
                              output_path, fmt=fmt, fps=args.fps)
    else:
        save_side_by_side_frames(tracking_df, video_frames, args.label, t_meta['game_time'],
                                 output_path, fmt=fmt, frame_indices=args.frames)


if __name__ == '__main__':
    main()
