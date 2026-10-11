shader_type canvas_item;
render_mode unshaded;
uniform sampler2D SCREEN_TEXTURE : hint_screen_texture, filter_linear;

uniform float currentHot : hint_range(0.0,1.0);
uniform vec4 hotColor : source_color;

uniform float heatAmplitude : hint_range(0.0, 0.15);
uniform float heatLocalAmplitude;
uniform float heatPeriod;
uniform float heatPhaseShift;
uniform float heatUpperLimit: hint_range(0.5, 10.0);
uniform vec2 center = vec2(0.5, 0.5);


void fragment() {
	vec4 hotnessColor = (hotColor * currentHot);
	vec2 modifiedUVHot = SCREEN_UV;
	
	float aspect_ratio = SCREEN_PIXEL_SIZE.y/SCREEN_PIXEL_SIZE.x;
	vec2 scaled_modifiedUVHot = (modifiedUVHot -vec2(0.0, 0.5)) / vec2(1.0, aspect_ratio) + vec2(0,0.5); 
	// Explicit min/max preserves the original expression's bounds without an
	// undefined clamp(min > max) call in GLSL/Cg.
	float heat_envelope = min(max(1.0 - scaled_modifiedUVHot.y * heatUpperLimit, 0.0), -0.5);
	
	scaled_modifiedUVHot.x -= (((scaled_modifiedUVHot.y) * heatAmplitude)*
		sin(heatPeriod * (scaled_modifiedUVHot.y - (TIME * 0.016 * heatPhaseShift)))) *
		heat_envelope *
		currentHot;
	
	COLOR = texture(SCREEN_TEXTURE, scaled_modifiedUVHot);
	
	
	COLOR.rgb += hotnessColor.rgb * hotnessColor.a;
}
