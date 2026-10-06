#pragma once
#include "glover_launcher_design.hpp"
// Compatibility adapter for the shared Rocket mod pages. The approved Glover
// widgets remain the single source of colour, typography and slider geometry.
namespace rocket::ui::theme {
inline bool button(const char* text, ImVec2 size={0,0}) {
    if (size.x < 0) size.x=ImGui::GetContentRegionAvail().x;
    if (size.y <= 0) size.y=38;
    return glover::launcher::design::race_button(text,size,false,false,true);
}
inline bool slider_float(const char* id,float* value,float low,float high,const char* format) {
    return glover::launcher::design::slider_float(id,value,low,high,format);
}
struct Card {
    Card(const char* id,const char* title=nullptr) { glover::launcher::design::begin_card(id,title); }
    ~Card() { glover::launcher::design::end_card(); }
};
}
