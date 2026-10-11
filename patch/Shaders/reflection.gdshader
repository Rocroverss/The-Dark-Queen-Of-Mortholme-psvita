shader_type canvas_item;

uniform vec4 color1 = vec4(0.05, 0.05, 0.2, 0.5);
uniform vec4 color2 = vec4(0.04,0.04,0.14, 0.1);

uniform float gradient_scale = 2.5;

void fragment() {
	vec4 tex = texture(TEXTURE, UV);
	
	float mixValue = (abs(UV.y - 1.0) + 0.1) * gradient_scale;
	
	vec4 color = mix(color1,color2,mixValue);
	
	COLOR = vec4(mix(color.rgb, tex.rgb, color.a), tex.a);
}
