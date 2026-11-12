#include "OsuOptionsMenu.h"

#include "Engine.h"
#include "Environment.h"
#include "ConVar.h"
#include "ResourceManager.h"
#include "Sound.h"
#include "SoundEngine.h"
#include "Font.h"
#include "CBaseUICheckbox.h"
#include "CBaseUITextbox.h"
#include "CBaseUILabel.h"
#include "CBaseUIScrollView.h"
#include "CBaseUIContainer.h"
#include "Osu.h"
#include "OsuBeatmapStandard.h"
#include "OsuUIButton.h"
#include "OsuUIContextMenu.h"
#include "OsuTimingAudioSetup.h"
#include "OsuTimingAudioHUD.h"
#include "OsuTimingAudioHudControls.h"
#include "OsuUISlider.h"
#include "OsuTooltipOverlay.h"
#include <algorithm>
#include <cctype>

static const char *timingWidthNames[] = {"Fixed milliseconds", "Map-relative fraction", "Adaptive spread"};

void OsuOptionsMenu::addTimingAudioOptions()
{
	const size_t firstElement = m_elements.size();
	addSubSection("Applied Timing Setup");
	m_timingAudioSetupReference = addLabel("Reference and band");
	m_elements.back().searchTags = "timing audio status applied setup";
	m_timingAudioSetupBand = addLabel("Band status");
	m_elements.back().searchTags = "timing audio status applied setup";
	m_timingAudioSetupLearning = addLabel("Learned spread");
	m_elements.back().searchTags = "timing audio status applied setup";
	addButton("Copy applied timing setup")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onCopyTimingAudioSetup));
	m_elements.back().searchTags = "timing audio copy status applied reference silent band spread";
	addLabel("Apply edits with Ctrl+Enter or the button below.");
	m_timingAudioStatus = addLabel("Editor matches applied settings.");
	m_elements.back().searchTags = "timing audio status";
	addButton("Apply timing settings to game")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioApply));
	m_elements.back().searchTags = "timing audio apply target gain reference width adaptive half-life startup gate break cue";
	addSubSection("Live Timing Debug Capture");
	for (const auto &control : OsuTimingAudioHudControls::controls())
	{
		if (control.group != OsuTimingAudioHudControls::CAPTURE) continue;
		auto *var = convar->getConVarByName(control.name);
		if (control.kind == OsuTimingAudioHudControls::CaptureKey) addKeyBindButton(control.label, var);
		else addCheckbox(control.label, control.help, var);
		m_elements.back().searchTags = UString::format("%s %s", control.name, control.help);
	}
	addButton("Mark problem")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onMarkTimingCapture));
	m_elements.back().searchTags = "timing capture report screenshot marker";
	addSubSection("Timing Audio Reference and Band");
	addLabel("Target 0 is center. Negative is early.");
	addLabel("Targets 1, 2 and 3 use the 300, 100 and 50 edges.");
	addLabel("Adaptive startup width and later idle widening are independent.");
	for (const auto &spec : OsuTimingAudioSettings::specs())
	{
		const std::string key = spec.name;
		if (key == "osu_timing_audio_muted") continue;
		if (key == "osu_timing_audio_idle_forgiveness")
		{
			addSubSection("Adaptive Idle Widening");
			addLabel("Idle tuning applies after two accepted hits in Adaptive spread.");
		}
		if (key == "osu_timing_audio_fixed_hits")
		{
			addSubSection("Timing Audio Learning and Breaks");
			addLabel("Changes to weighting, startup averaging or break detection reset learning.");
			addLabel("Recent warmup needs Recent reference and its mute toggle.");
		}
		if (key == "osu_timing_audio_volume")
		{
			addSubSection("Timing Audio Cues and Mute");
			m_timingAudioMuteButton = addButton("Mute training cues (keep learning)");
			m_timingAudioMuteButton->setText("Mute cues (keep learning)");
			m_timingAudioMuteButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioMute));
			m_elements.back().searchTags = "timing audio mute";
		}
		TimingAudioField field = {&spec, NULL, NULL, NULL};
		const auto &help = convar->getConVarByName(spec.name)->getHelpstring();
		const UString tags = UString::format("timing audio %s %s %s", spec.label, spec.name, help.toUtf8());
		if (key == "osu_timing_audio_deadzone_mode")
		{
			m_timingAudioWidthButton = addButton("Silent width");
			m_timingAudioWidthButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioWidth));
		}
		else if (spec.type == OsuTimingAudioSettings::BOOLEAN)
			field.checkbox = addCheckbox(spec.label, help, NULL);
		else
		{
			field.label = addLabel(spec.label);
			m_elements.back().searchTags = tags;
			field.textbox = addTextbox("", (ConVar*)NULL);
		}
		m_elements.back().searchTags = tags;
		m_timingAudioFields.push_back(field);
	}
	addLabel("Cue gain ignores Effects; uses Master.");
	addLabel("Retry to reload edits to the same file.");
	addButton("Apply timing settings to game")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioApply));
	m_elements.back().searchTags = "timing audio apply target gain reference width adaptive half-life startup gate break cue";
	addButton("Timing defaults into editor (then Apply)")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioDefaults));
	static_cast<CBaseUIButton*>(m_elements.back().elements[0])->setText("Put defaults in editor (then Apply)");
	m_elements.back().searchTags = "timing audio defaults";
	m_timingAudioFileButtons[0] = addButton("Choose available early cue...");
	m_timingAudioFileButtons[0]->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioEarlyFile));
	m_elements.back().searchTags = "timing audio early sound cue";
	m_timingAudioFileButtons[1] = addButton("Choose available late cue...");
	m_timingAudioFileButtons[1]->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioLateFile));
	m_elements.back().searchTags = "timing audio late sound cue";
	addButton("Preview draft early cue")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioPreviewEarly));
	m_elements.back().searchTags = "timing audio preview early";
	addButton("Preview draft late cue")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioPreviewLate));
	m_elements.back().searchTags = "timing audio preview late";
	using namespace OsuTimingAudioHudControls;
	Group group = BAR;
	for (const Control &control : controls())
	{
		if (control.group == CAPTURE) continue;
		if (control.group != group)
		{
			group = control.group;
			addSubSection(group == TIMING ? "Timing Audio HUD"
				: (group == APPEARANCE ? "Timing Overlay Appearance" : "Hit Error Bar Appearance and Layout"));
		}
		ConVar *var = convar->getConVarByName(control.name);
		if (control.kind == Toggle) addCheckbox(control.label, control.help, var);
		else if (control.kind == View)
		{
			m_timingAudioViewButton = addButton(control.label);
			m_elements.back().cvar = var;
			m_timingAudioViewButton->setTooltipText(control.help);
			m_timingAudioViewButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioView));
			updateTimingAudioViewButton();
		}
		else
		{
			auto *slider = addSlider(control.label, control.min, control.max, var);
			m_elements.back().timingHudHelp = control.help;
			slider->setKeyDelta(control.kind == Integer ? 1.0f : (control.kind == Precise ? 0.001f : 0.01f));
			if (control.kind == Integer)
				slider->setChangeCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onSliderChangeInt));
			else if (control.kind == Precise)
				slider->setChangeCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingHudPreciseSlider));
			else if (control.kind == BarScale || control.kind == URScale)
			{
				slider->setChangeCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onSliderChangePercent));
				if (control.kind == BarScale) m_hudHiterrorbarScaleSlider = slider;
				else m_hudHiterrorbarURScaleSlider = slider;
			}
		}
		m_elements.back().searchTags = UString::format("%s %s", control.name, control.help);
	}
	addSubSection("Timing Audio Profiles");
	addLabel("Profiles store audio settings. HUD preferences are saved with Options.");
	addLabel("Apply edits before saving a profile.");
	addLabel("Profile name:");
	m_timingAudioProfileName = addTextbox("", (ConVar*)NULL);
	m_elements.back().searchTags = "timing audio profile name";
	m_timingAudioProfileStatus = addLabel("Profile actions report here.");
	const size_t profileStatusRow = m_elements.size() - 1;
	m_elements.back().searchTags = "timing audio profile status";
	addButton("Save applied settings as named profile")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioSaveProfile));
	static_cast<CBaseUIButton*>(m_elements.back().elements[0])->setText("Save applied profile");
	m_elements.back().searchTags = "timing audio profile save";
	m_timingAudioLoadButton = addButton("Load and apply saved profile...");
	m_timingAudioLoadButton->setText("Load and apply profile...");
	m_timingAudioLoadButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioLoadProfile));
	m_elements.back().searchTags = "timing audio profile load";
	addButton("Delete named profile (confirmation required)")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioDeleteProfile));
	static_cast<CBaseUIButton*>(m_elements.back().elements[0])->setText("Delete named profile...");
	m_elements.back().searchTags = "timing audio profile delete";
	// A confirmation must survive every search that keeps its action button.
	for (size_t i = profileStatusRow + 1; i < m_elements.size(); ++i)
	{
		m_elements[profileStatusRow].searchTags.append(" ");
		m_elements[profileStatusRow].searchTags.append(m_elements[i].searchTags);
		for (CBaseUIElement *element : m_elements[i].elements)
		{
			m_elements[profileStatusRow].searchTags.append(" ");
			m_elements[profileStatusRow].searchTags.append(element->getName());
		}
	}
	syncTimingAudio(OsuTimingAudioSettings::capture());
	for (size_t i = firstElement; i < m_elements.size(); ++i) m_elements[i].searchTags.append(" timing audio");
}

void OsuOptionsMenu::syncTimingAudio(const OsuTimingAudioSettings::Values &values)
{
	for (TimingAudioField &field : m_timingAudioFields)
	{
		const auto found = values.find(field.spec->name);
		if (found == values.end()) continue;
		if (field.checkbox != NULL)
		{
			long double value = 0;
			OsuTimingAudioSettings::number(found->second, value);
			field.checkbox->setChecked(value > 0, false);
		}
		if (field.textbox != NULL) field.textbox->setText(found->second.c_str());
	}
	const auto width = values.find("osu_timing_audio_deadzone_mode");
	long double mode = 0;
	if (width != values.end()) OsuTimingAudioSettings::number(width->second, mode);
	m_timingAudioWidth = mode >= 0 && mode <= 2 ? (int)mode : 0;
	m_timingAudioWidthButton->setText(UString::format("Silent width: %s", timingWidthNames[m_timingAudioWidth]));
	m_timingAudioEditState = 0;
	m_timingAudioSetupNextUpdate = 0;
}

OsuTimingAudioView OsuOptionsMenu::appliedTimingAudioView(const OsuTimingAudioSettings::Values &applied) const
{
	OsuTimingAudioView view;
	if (applied.at("osu_timing_audio") == "0")
		view.evaluation.phase = OsuTimingAudioEvaluation::OFF;
	else if (m_osu->isInPlayMode())
	{
		const auto *beatmap = dynamic_cast<const OsuBeatmapStandard*>(m_osu->getSelectedBeatmap());
		if (beatmap != NULL && beatmap->getMusic() != NULL)
		{
			const auto *duration = convar->getConVarByName("osu_hud_hiterrorbar_timing_audio_recent_seconds");
			const double seconds = OsuTimingAudioHUD::recentDuration(duration->getFloat());
			view = beatmap->getTimingAudioView(OsuTimingAudioView::AUDIO_ESTIMATE, seconds, true);
		}
	}
	return view;
}

void OsuOptionsMenu::onCopyTimingAudioSetup()
{
	const auto applied = OsuTimingAudioSettings::capture();
	const auto view = appliedTimingAudioView(applied);
	const auto mode = OsuTimingAudioView::fromSetting(convar->getConVarByName("osu_hud_hiterrorbar_timing_audio_view")->getInt());
	std::string text = OsuTimingAudioSetup::copyText(applied, view, mode, timingAudioDraft() != applied);
	const auto enabled = [](const char *key) { return convar->getConVarByName(key)->getBool(); };
	const auto *beatmap = m_osu->isInPlayMode() ? dynamic_cast<const OsuBeatmapStandard*>(m_osu->getSelectedBeatmap()) : NULL;
	const char *hudStatus = "eligible to draw selected view";
	if (!enabled("osu_hud_hiterrorbar_timing_audio")) hudStatus = "timing overlay disabled";
	else if (!enabled("osu_draw_hiterrorbar")) hudStatus = "hit error bar disabled";
	else if (!enabled("osu_draw_hud") && enabled("osu_hud_shift_tab_toggles_everything")) hudStatus = "HUD hidden";
	else if (!enabled("osu_draw_hiterrorbar_bottom") && !enabled("osu_draw_hiterrorbar_top")
		&& !enabled("osu_draw_hiterrorbar_left") && !enabled("osu_draw_hiterrorbar_right")) hudStatus = "no bar placements enabled";
	else if (view.evaluation.phase == OsuTimingAudioEvaluation::OFF) hudStatus = "timing audio off";
	else if (beatmap == NULL || view.speed <= 0) hudStatus = "waiting for gameplay";
	else if (beatmap->isSpinnerActive() && enabled("osu_hud_hiterrorbar_hide_during_spinner")) hudStatus = "bar hidden during spinner";
	else if (convar->getConVarByName("osu_hud_hiterrorbar_alpha")->getFloat() <= 0
		|| convar->getConVarByName("osu_hud_hiterrorbar_timing_audio_alpha")->getFloat() <= 0) hudStatus = "overlay opacity is zero";
	text += std::string("HUD status ") + hudStatus + "\n";
	const auto *duration = convar->getConVarByName("osu_hud_hiterrorbar_timing_audio_recent_seconds");
	text += "Recent window duration " + OsuTimingAudioSetup::number(OsuTimingAudioHUD::recentDuration(duration->getFloat())) + " s\n";
	text += "\nMcOsu version " + std::string(Osu::version->getString().toUtf8()) + "\n";
	text += "HUD/volume preferences (separate from named profiles)\n";
	const auto appendSetting = [&text](const char *name)
	{
		text += std::string(name) + " = " + convar->getConVarByName(name)->getString().toUtf8() + "\n";
	};
	for (const auto &control : OsuTimingAudioHudControls::controls()) appendSetting(control.name);
	for (const char *name : {"osu_draw_hud", "osu_hud_scale", "osu_hud_shift_tab_toggles_everything",
		"osu_volume_master", "osu_volume_master_inactive"}) appendSetting(name);
	env->setClipBoardText(text.c_str());
	m_osu->getNotificationOverlay()->addNotification("Applied timing setup copied.", 0xffffffff, false, 1.5f);
}

void OsuOptionsMenu::onMarkTimingCapture()
{
	m_osu->markTimingCapture();
}

OsuTimingAudioSettings::Values OsuOptionsMenu::timingAudioDraft() const
{
	auto values = OsuTimingAudioSettings::capture();
	for (const TimingAudioField &field : m_timingAudioFields)
	{
		if (field.checkbox != NULL) values[field.spec->name] = field.checkbox->isChecked() ? "1" : "0";
		if (field.textbox != NULL) values[field.spec->name] = field.textbox->getText().toUtf8();
	}
	values["osu_timing_audio_deadzone_mode"] = std::to_string(m_timingAudioWidth);
	return values;
}

void OsuOptionsMenu::updateTimingAudioEditor()
{
	const auto draft = timingAudioDraft();
	const auto current = OsuTimingAudioSettings::capture();
	if (engine->getTime() >= m_timingAudioSetupNextUpdate)
	{
		const auto summary = OsuTimingAudioSetup::summarize(current, appliedTimingAudioView(current));
		m_timingAudioSetupReference->setText(summary.reference.c_str());
		m_timingAudioSetupBand->setText(summary.band.c_str());
		m_timingAudioSetupLearning->setText(summary.spread.c_str());
		m_timingAudioSetupNextUpdate = engine->getTime() + 0.25;
	}
	int editState = draft != current ? 1 : 0;
	for (const auto &spec : OsuTimingAudioSettings::specs())
		if (spec.restarts && draft.at(spec.name) != current.at(spec.name)) editState = 2;
	if (editState != m_timingAudioEditState)
	{
		m_timingAudioEditState = editState;
		m_timingAudioStatus->setText(editState == 2 ? "Unapplied edits; learning can restart."
			: editState == 1 ? "Unapplied edits. Apply to use." : "Editor matches game settings.");
		m_timingAudioStatus->setTextColor(0xffffffff);
	}
	m_timingAudioMuteButton->setText(convar->getConVarByName("osu_timing_audio_muted")->getBool()
		? "Unmute cues (keep learning)" : "Mute cues (keep learning)");
	const bool tooltipsAllowed = m_options->isMouseInside() && !m_contextMenu->isVisible();
	const auto &visible = m_options->getContainer()->getElements();
	const auto hovered = [&](CBaseUIElement *element)
	{
		return tooltipsAllowed && element->isMouseInside() && std::find(visible.begin(), visible.end(), element) != visible.end();
	};
	const auto tooltip = [&](const UString &help, const UString &range, const char *inactive, const char *apply)
	{
		auto *overlay = m_osu->getTooltipOverlay();
		overlay->begin();
		overlay->addLine(help);
		if (range.length() > 0) overlay->addLine(range);
		if (inactive != NULL) overlay->addLine(inactive);
		if (apply != NULL) overlay->addLine(apply);
		overlay->end();
	};
	bool tooltipShown = false;
	for (const TimingAudioField &field : m_timingAudioFields)
	{
		if (field.textbox == NULL) continue;
		const std::string key = field.spec->name;
		const char *inactive = NULL;
		if (key == "osu_timing_audio_target" && draft.at("osu_timing_audio_recent") != "0") inactive = "Select Beatmap reference.";
		else if (key == "osu_timing_audio_deadzone" && m_timingAudioWidth == 1) inactive = "Select Fixed milliseconds or Adaptive spread.";
		else if (key == "osu_timing_audio_deadzone_fraction" && m_timingAudioWidth != 1) inactive = "Select Map-relative fraction.";
		else if (key.find("osu_timing_audio_deadzone_adaptive_") == 0 && m_timingAudioWidth != 2) inactive = "Select Adaptive spread.";
		else if (key.find("osu_timing_audio_idle_") == 0)
		{
			if (m_timingAudioWidth != 2) inactive = "Select Adaptive spread.";
			else if (draft.at("osu_timing_audio_idle_forgiveness") != "1") inactive = "Enable Widen adaptive band during idle.";
		}
		else if (key == "osu_timing_audio_silent_startup_hits")
		{
			if (draft.at("osu_timing_audio_recent") != "1") inactive = "Select Recent reference.";
			else if (draft.at("osu_timing_audio_silent_startup") != "1") inactive = "Enable Mute Recent during startup.";
		}
		else if (key == "osu_timing_audio_half_life_seconds" && draft.at("osu_timing_audio_fixed_hits") != "0") inactive = "Select time adaptation.";
		else if (key == "osu_timing_audio_half_life_hits" && draft.at("osu_timing_audio_fixed_hits") != "1") inactive = "Select hit-count adaptation.";
		field.textbox->setEnabled(inactive == NULL);
		UString label = field.spec->label;
		if (inactive != NULL) label.append(" (inactive)");
		if (field.label->getText() != label) field.label->setText(label);
		if (!tooltipShown && (hovered(field.label) || hovered(field.textbox)))
		{
			const auto &help = convar->getConVarByName(field.spec->name)->getHelpstring();
			const UString range = field.spec->type == OsuTimingAudioSettings::FILENAME ? UString()
				: UString::format("Range %.6g to %.6g", (double)field.spec->min, (double)field.spec->max);
			tooltip(help, range, inactive, field.spec->restarts ? "Apply resets learning." : "Apply keeps learning.");
			tooltipShown = true;
		}
	}
	if (tooltipsAllowed && !tooltipShown)
		for (const OPTIONS_ELEMENT &row : m_elements)
			if (row.timingHudHelp != NULL && (hovered(row.elements[0]) || hovered(row.elements[1])))
			{
				tooltip(row.timingHudHelp, UString(), NULL, "Applies immediately.");
				break;
			}
}

void OsuOptionsMenu::timingAudioStatus(UString text, bool error)
{
	for (CBaseUILabel *label : {m_timingAudioStatus, m_timingAudioProfileStatus})
	{
		UString visible = text;
		const float available = label->getSize().x - 10;
		if (available > 0 && label->getFont()->getStringWidth(visible) > available)
		{
			while (visible.length() > 0)
			{
				UString candidate = visible;
				candidate.append("...");
				if (label->getFont()->getStringWidth(candidate) <= available) break;
				visible = visible.substr(0, visible.length() - 1);
			}
			visible.append("...");
		}
		label->setText(visible);
		label->setTextColor(error ? 0xffff6666 : 0xffffffff);
	}
	if (error) m_osu->getNotificationOverlay()->addNotification(text, 0xffff6666, false, 1.5f);
}

void OsuOptionsMenu::onTimingAudioApply()
{
	m_timingAudioConfirm.clear();
	const std::string error = OsuTimingAudioSettings::apply(timingAudioDraft());
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	syncTimingAudio(OsuTimingAudioSettings::capture());
	m_timingAudioConfirm.clear();
	timingAudioStatus("Applied to game.");
}

void OsuOptionsMenu::onTimingAudioDefaults()
{
	m_timingAudioConfirm.clear();
	syncTimingAudio(OsuTimingAudioSettings::capture(true));
	timingAudioStatus("Defaults in editor. Apply to use.");
}

void OsuOptionsMenu::onTimingAudioMute()
{
	m_timingAudioConfirm.clear();
	ConVar *mute = convar->getConVarByName("osu_timing_audio_muted");
	mute->setValue(!mute->getBool());
	timingAudioStatus(mute->getBool() ? "Muted; learning continues if enabled." : "Unmuted; gain unchanged.");
}

void OsuOptionsMenu::onTimingAudioWidth()
{
	m_timingAudioConfirm.clear();
	m_contextMenu->setPos(m_timingAudioWidthButton->getPos());
	m_contextMenu->setRelPos(m_timingAudioWidthButton->getRelPos());
	m_contextMenu->begin(m_timingAudioWidthButton->getSize().x);
	for (int i = 0; i < 3; ++i) m_contextMenu->addButton(timingWidthNames[i], i);
	m_contextMenu->end(false, false);
	m_contextMenu->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioWidthSelected));
}

void OsuOptionsMenu::onTimingAudioWidthSelected(UString, int id)
{
	if (id < 0 || id > 2) return;
	m_timingAudioWidth = id;
	m_timingAudioWidthButton->setText(UString::format("Silent width: %s", timingWidthNames[id]));
}

void OsuOptionsMenu::onTimingAudioSaveProfile()
{
	const std::string name = m_timingAudioProfileName->getText().toUtf8();
	if (!OsuTimingAudioSettings::validProfileName(name)) { timingAudioStatus("Enter a profile name without brackets or control characters.", true); return; }
	OsuTimingAudioSettings::Profiles profiles;
	std::string error = OsuTimingAudioSettings::readProfiles(profiles);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	const auto values = OsuTimingAudioSettings::capture();
	if (timingAudioDraft() != values) { timingAudioStatus("Apply or discard edits before saving a profile.", true); return; }
	error = OsuTimingAudioSettings::validate(values);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	if (profiles.count(name) && (m_timingAudioConfirm != "save:" + name || m_timingAudioConfirmValues != values || engine->getTime() > m_timingAudioConfirmUntil))
	{
		m_timingAudioConfirm = "save:" + name; m_timingAudioConfirmValues = values; m_timingAudioConfirmUntil = engine->getTime() + 10;
		timingAudioStatus("Click Save again (10s) to overwrite."); return;
	}
	profiles[name] = values;
	error = OsuTimingAudioSettings::writeProfiles(profiles);
	m_timingAudioConfirm.clear();
	timingAudioStatus(error.empty() ? UString::format("Saved: %s", name.c_str()) : UString(error.c_str()), !error.empty());
}

void OsuOptionsMenu::onTimingAudioLoadProfile()
{
	m_timingAudioConfirm.clear();
	m_contextMenu->setVisible2(false);
	const std::string error = OsuTimingAudioSettings::readProfiles(m_timingAudioProfiles);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	if (m_timingAudioProfiles.empty()) { timingAudioStatus("No saved timing profiles yet."); return; }
	m_contextMenu->setPos(m_timingAudioLoadButton->getPos());
	m_contextMenu->setRelPos(m_timingAudioLoadButton->getRelPos());
	m_contextMenu->begin(m_timingAudioLoadButton->getSize().x);
	int id = 0;
	for (const auto &profile : m_timingAudioProfiles) m_contextMenu->addButton(profile.first.c_str(), id++);
	m_contextMenu->end(false, false);
	m_contextMenu->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioProfileSelected));
}

void OsuOptionsMenu::onTimingAudioProfileSelected(UString name, int)
{
	OsuTimingAudioSettings::Profiles profiles;
	std::string error = OsuTimingAudioSettings::readProfiles(profiles);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	const auto found = profiles.find(name.toUtf8());
	if (found == profiles.end()) { timingAudioStatus("Profile no longer available; reopen the list.", true); return; }
	error = OsuTimingAudioSettings::apply(found->second);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	syncTimingAudio(OsuTimingAudioSettings::capture());
	m_timingAudioProfileName->setText(name);
	m_timingAudioConfirm.clear();
	timingAudioStatus(UString::format("Loaded: %s", name.toUtf8()));
}

void OsuOptionsMenu::onTimingAudioDeleteProfile()
{
	const std::string name = m_timingAudioProfileName->getText().toUtf8();
	OsuTimingAudioSettings::Profiles profiles;
	std::string error = OsuTimingAudioSettings::readProfiles(profiles);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	if (!profiles.count(name)) { timingAudioStatus("No saved profile with this name.", true); return; }
	if (m_timingAudioConfirm != "delete:" + name || m_timingAudioConfirmValues != profiles.at(name) || engine->getTime() > m_timingAudioConfirmUntil)
	{
		m_timingAudioConfirm = "delete:" + name; m_timingAudioConfirmValues = profiles.at(name); m_timingAudioConfirmUntil = engine->getTime() + 10;
		timingAudioStatus("Click Delete again (10s) to confirm."); return;
	}
	profiles.erase(name);
	error = OsuTimingAudioSettings::writeProfiles(profiles);
	m_timingAudioConfirm.clear();
	timingAudioStatus(error.empty() ? "Deleted timing profile; current game settings kept." : error.c_str(), !error.empty());
}

void OsuOptionsMenu::onTimingAudioPreviewEarly() { previewTimingAudio(false); }
void OsuOptionsMenu::onTimingAudioPreviewLate() { previewTimingAudio(true); }

void OsuOptionsMenu::previewTimingAudio(bool late)
{
	m_timingAudioConfirm.clear();
	const auto values = timingAudioDraft();
	const std::string error = OsuTimingAudioSettings::validate(values);
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	const int index = late ? 1 : 0;
	Sound *sound = engine->getResourceManager()->loadSound(values.at(late ? "osu_timing_audio_late_sound" : "osu_timing_audio_early_sound").c_str(), "");
	if (sound == NULL || !sound->isReady())
	{
		if (sound != NULL) engine->getResourceManager()->destroyResource(sound);
		timingAudioStatus("Cannot load draft cue for preview.", true); return;
	}
	if (m_timingAudioPreview[index] != NULL) engine->getResourceManager()->destroyResource(m_timingAudioPreview[index]);
	m_timingAudioPreview[index] = sound;
	long double gain = 0; OsuTimingAudioSettings::number(values.at("osu_timing_audio_volume"), gain);
	sound->setVolume((float)gain);
	const bool started = engine->getSound()->play(sound);
	timingAudioStatus(started ? "Draft cue preview started (uses Master and cue gain)." : "Cue preview could not start.", !started);
}

void OsuOptionsMenu::onTimingAudioEarlyFile() { chooseTimingAudioFile(false); }
void OsuOptionsMenu::onTimingAudioLateFile() { chooseTimingAudioFile(true); }

void OsuOptionsMenu::chooseTimingAudioFile(bool late)
{
	m_timingAudioConfirm.clear();
	if (!env->directoryExists("sounds/")) { timingAudioStatus("No sounds/ folder is available.", true); return; }
	m_timingAudioFileKey = late ? "osu_timing_audio_late_sound" : "osu_timing_audio_early_sound";
	OsuUIButton *anchor = m_timingAudioFileButtons[late ? 1 : 0];
	m_contextMenu->setPos(anchor->getPos());
	m_contextMenu->setRelPos(anchor->getRelPos());
	m_contextMenu->begin(anchor->getSize().x);
	int count = 0;
	auto files = env->getFilesInFolder("sounds/");
	std::sort(files.begin(), files.end(), [](const UString &a, const UString &b) { return std::string(a.toUtf8()) < std::string(b.toUtf8()); });
	for (const UString &file : files)
	{
		std::string name = file.toUtf8();
		std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
		if (name.size() >= 4 && name.substr(name.size() - 4) == ".wav") { m_contextMenu->addButton(file, count); ++count; }
	}
	m_contextMenu->end(false, false);
	m_contextMenu->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioFileSelected));
	if (count == 0) { m_contextMenu->setVisible2(false); timingAudioStatus("No WAVs found. Enter a relative cue filename above.", true); }
}

void OsuOptionsMenu::onTimingAudioFileSelected(UString name, int)
{
	for (const TimingAudioField &field : m_timingAudioFields)
		if (m_timingAudioFileKey == field.spec->name && field.textbox != NULL) field.textbox->setText(name);
}

bool OsuOptionsMenu::timingAudioEditing() const
{
	std::string search = m_sSearchString.toUtf8();
	std::transform(search.begin(), search.end(), search.begin(), [](unsigned char c) { return std::tolower(c); });
	if (search.find("timing") != std::string::npos) return true;
	const auto &visible = m_options->getContainer()->getElements();
	if (m_timingAudioProfileName->isActive() && std::find(visible.begin(), visible.end(), m_timingAudioProfileName) != visible.end()) return true;
	for (const TimingAudioField &field : m_timingAudioFields)
		if ((field.textbox != NULL && field.textbox->isActive() && std::find(visible.begin(), visible.end(), field.textbox) != visible.end())
			|| (field.checkbox != NULL && field.checkbox->isActive() && std::find(visible.begin(), visible.end(), field.checkbox) != visible.end())) return true;
	return false;
}
