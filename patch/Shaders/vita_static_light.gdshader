shader_type canvas_item;
render_mode unshaded;

uniform sampler2D room_screen : hint_screen_texture, filter_linear;
uniform vec4 light_color : source_color = vec4(1.0);
uniform float light_energy = 1.0;

void fragment() {
    vec4 scene = texture(room_screen, SCREEN_UV);
    vec4 light = texture(TEXTURE, UV);
    COLOR = vec4(scene.rgb * (vec3(1.0) + light.rgb * light_color.rgb * light_energy), light.a);
}
