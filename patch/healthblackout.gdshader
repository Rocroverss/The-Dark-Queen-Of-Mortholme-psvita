shader_type canvas_item;
render_mode unshaded;

uniform vec2 circle_coords;
uniform float circle_size : hint_range(0.0, 2.1);
uniform float screen_width;
uniform float screen_height;
uniform float alpha: hint_range(0.0, 1.0);
uniform float feather: hint_range(0.0, 2.1);

// Vita adaptation: scalar radius and explicit cubic feather ramp.
// Keep the existing material parameters and ellipse/opacity semantics.
void fragment() {
 float safe_width = max(screen_width, 1.0);
 float safe_height = max(screen_height, 1.0);
 float dx = (circle_coords.x - UV.x * safe_width) / (safe_height * 5.0);
 float dy = circle_coords.y / safe_height - UV.y;
 float radius = sqrt(dx * dx + dy * dy);
 float ramp = clamp((radius - circle_size) / max(feather, 0.00001), 0.0, 1.0);
 COLOR.a = ramp * ramp * (3.0 - 2.0 * ramp) * alpha;
}
