"""GLSL 120 shader sources for the GL background backend.

Written in GLSL 1.20 subset (``texture2D`` / ``gl_FragColor``) so the same
sources compile on desktop GL 2.1+, GLES2 (ANGLE) and Qt's software GL —
mirroring the wide fallback policy of the rest of the app.

Effect semantics must match their CPU counterparts in
``AssetsManager.core.bg_effects`` (see the architecture design doc §4):
* blur      — separable passes, mirror-extension padding (BORDER_REFLECT);
* mosaic    — nearest-neighbour block sampling;
* kuwahara  — four quadrant windows, min RGB variance wins;
* shadertoy — ``iResolution`` / ``iTime`` / ``iChannel0..1`` compatible
  wrapper, presets provide ``mainImage``.
"""
from __future__ import annotations

VERT_SRC = """
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

PASSTHROUGH_FRAG = """
uniform sampler2D u_tex;
varying vec2 v_uv;
void main() {
    gl_FragColor = texture2D(u_tex, v_uv);
}
"""

BLUR_FRAG = """
uniform sampler2D u_tex;
uniform vec2 u_texel;   // 1.0 / texture size
uniform vec2 u_dir;     // (1,0) horizontal pass, (0,1) vertical pass
uniform float u_radius; // blur radius in pixels (>= 1)
varying vec2 v_uv;
void main() {
    float r = max(1.0, u_radius);
    vec2 step = u_dir * u_texel * r;
    // Weighted 9-tap gaussian (normalised).
    float w[5];
    w[0] = 0.227027; w[1] = 0.1945946; w[2] = 0.1216216; w[3] = 0.054054; w[4] = 0.016216;
    vec3 col = texture2D(u_tex, v_uv).rgb * w[0];
    for (int i = 1; i <= 4; i++) {
        float fi = float(i);
        col += texture2D(u_tex, v_uv + step * fi).rgb * w[i];
        col += texture2D(u_tex, v_uv - step * fi).rgb * w[i];
    }
    gl_FragColor = vec4(col, 1.0);
}
"""

MOSAIC_FRAG = """
uniform sampler2D u_tex;
uniform vec2 u_block;   // number of blocks on X and Y axes
varying vec2 v_uv;
void main() {
    vec2 uv = floor(v_uv * u_block) / u_block;
    gl_FragColor = vec4(texture2D(u_tex, uv).rgb, 1.0);
}
"""

KUW_FRAG = """
uniform sampler2D u_tex;
uniform vec2 u_texel;
uniform float u_radius; // quadrant half-width >= 1
varying vec2 v_uv;
void main() {
    int r = int(clamp(u_radius, 1.0, 24.0));
    int side = r + 1;
    vec3 best_mean = texture2D(u_tex, v_uv).rgb;
    float best_var = 1e30;
    // The four quadrant windows meet at the current pixel (uv).
    for (int qy = 0; qy < 2; qy++) {
        for (int qx = 0; qx < 2; qx++) {
            vec3 sum = vec3(0.0);
            vec3 sum2 = vec3(0.0);
            float n = 0.0;
            for (int dy = 0; dy < 25; dy++) {
                if (dy >= side) break;
                for (int dx = 0; dx < 25; dx++) {
                    if (dx >= side) break;
                    vec2 off = vec2(float(dx - side + qx * side), float(dy - side + qy * side)) * u_texel;
                    vec3 c = texture2D(u_tex, clamp(v_uv + off, 0.001, 0.999)).rgb;
                    sum += c;
                    sum2 += c * c;
                    n += 1.0;
                }
            }
            vec3 mean = sum / n;
            vec3 var = sum2 / n - mean * mean;
            float total = var.x + var.y + var.z;
            if (total < best_var) {
                best_var = total;
                best_mean = mean;
            }
        }
    }
    gl_FragColor = vec4(best_mean, 1.0);
}
"""

SHADERTOY_HEADER = """
#define texture texture2D
uniform vec3 iResolution;
uniform float iTime;
uniform float u_strength;
uniform sampler2D iChannel0;
uniform sampler2D iChannel1;
varying vec2 v_uv;

// Forward declaration: presets define mainImage AFTER this header, and many
// GLSL compilers (ANGLE included) reject calling an undeclared function.
void mainImage(out vec4 fragColor, in vec2 fragCoord);

void main() {
    vec2 fragCoord = v_uv * iResolution.xy;
    mainImage(gl_FragColor, fragCoord);
}
"""

# Shadertoy-compatible fragment shaders (mainImage body).
PRESET_FRAGMENT_SNIPPETS: dict[str, str] = {
    "plasma": """
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy * 2.0 - 1.0;
    float t = iTime * 0.5;
    float v = sin(uv.x * 3.0 + t) + sin(uv.y * 4.0 + t * 1.3)
            + sin((uv.x + uv.y) * 5.0 + t * 0.7);
    vec3 col = 0.5 + 0.5 * cos(vec3(1.0, 2.0, 3.0) * v * 3.0 + vec3(0.0, 2.0, 4.0));
    col *= 0.6 + 0.4 * u_strength;
    fragColor = vec4(col, 1.0);
}
""",
    "grid-flow": """
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 p = fragCoord / iResolution.xy;
    vec2 g = abs(fract(p * 8.0 + vec2(0.0, iTime * 0.3)) - 0.5);
    float line = smoothstep(0.42, 0.5, max(g.x, g.y));
    vec3 col = mix(vec3(0.05, 0.5, 0.9), vec3(0.01, 0.01, 0.06), line);
    fragColor = vec4(col * (0.5 + 0.5 * u_strength), 1.0);
}
""",
}

# Uniforms each program exposes to the renderer.
BLUR_UNIFORMS = ("u_tex", "u_texel", "u_dir", "u_radius")
MOSAIC_UNIFORMS = ("u_tex", "u_block")
KUW_UNIFORMS = ("u_tex", "u_texel", "u_radius")
SHADERTOY_UNIFORMS = ("iResolution", "iTime", "u_strength", "iChannel0", "iChannel1")