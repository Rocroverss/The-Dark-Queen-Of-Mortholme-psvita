shader_type canvas_item;

uniform vec4 fxColor1 : source_color;
uniform float radius: hint_range(0.0, 2.0, 0.001) = 0.25;
uniform float color_str : hint_range(0.0, 1.0);

uniform float strength: hint_range(0.0, 0.1, 0.001) = 0.08;
uniform vec2 center = vec2(0.5, 0.5);
uniform vec2 hero_pos = vec2(0.25, 0.75);


uniform float aberration: hint_range(0.0, 1.0, 0.001) = 0.425;
uniform float width: hint_range(0.0, 0.1, 0.0001) = 0.04;
uniform float feather: hint_range(0.0, 1.0, 0.001) = 0.135;
uniform float intensity;

uniform sampler2D SCREEN_TEXTURE : hint_screen_texture, filter_linear;


float random(vec2 uv) {
    return fract(sin(dot(uv.xy,
        vec2(12.9898,78.233))) *
            43758.5453123);
}

float noise(vec2 uv) {
    vec2 uv_index = floor(uv);
    vec2 uv_fract = fract(uv);

    // Four corners in 2D of a tile
    float a = random(uv_index);
    float b = random(uv_index + vec2(1.0, 0.0));
    float c = random(uv_index + vec2(0.0, 1.0));
    float d = random(uv_index + vec2(1.0, 1.0));

    vec2 blur = smoothstep(vec2(0.0), vec2(1.0), uv_fract);

    return mix(a, b, blur.x) +
            (c - a) * blur.y * (1.0 - blur.x) +
            (d - b) * blur.x * blur.y;
}

float fbm(vec2 uv, vec2 dist_center, vec2 dist_hero_pos, float effect_radius, float effect_feather, float effect_width, float effect_intensity, float effect_time) {
    float amplitude = 0.7;
    float frequency = 10.0;
	float value = 0.0;
	
	float dist_both = (1.0 - smoothstep(effect_radius-effect_feather, effect_radius, length(dist_center))) * smoothstep(effect_radius - effect_width - effect_feather *1.3, effect_radius-effect_width , length(dist_center) * smoothstep(0.05, 0.11, length(dist_hero_pos)));

    vec2 safe_direction = dist_center / max(length(dist_center), 0.00001);
    for(int i = 0; i < 4; i++) {
        value += amplitude * noise(frequency * uv * -safe_direction + effect_time * 5.0);
        amplitude *= 0.5;
        frequency *= 2.0;
    }
	value = clamp(value, 0.5,1.0) * clamp(dist_both, 0.0, 1.0) * effect_intensity*effect_radius*effect_radius;
    return value;
}

void fragment() {
	vec2 st = SCREEN_UV;
	float aspect_ratio = SCREEN_PIXEL_SIZE.y/SCREEN_PIXEL_SIZE.x;
	vec2 scaled_st = (st -vec2(0.0, 0.5)) / vec2(1.0, aspect_ratio) + vec2(0,0.5); 
	vec2 dist_center = scaled_st - center;
	vec2 dist_hero_pos = scaled_st - hero_pos;
	float mask =  fbm(UV, dist_center, dist_hero_pos, radius, feather, width, intensity, TIME);
	vec2 safe_direction = dist_center / max(length(dist_center), 0.00001);
	vec2 offset = safe_direction * strength * mask;
	vec2 biased_st = scaled_st - offset;
	
	vec2 abber_vec = offset*aberration*mask;
	
	vec2 final_st = st*(1.0-mask) + biased_st*mask;

	vec4 red = texture(SCREEN_TEXTURE, final_st + abber_vec);
	vec4 blue = texture(SCREEN_TEXTURE, final_st - abber_vec);
	vec4 ori = texture(SCREEN_TEXTURE, final_st);
	COLOR = vec4(red.r, ori.g, blue.b, color_str);
	
	
	COLOR.rgb += fxColor1.rgb * fxColor1.a * mask;
}
