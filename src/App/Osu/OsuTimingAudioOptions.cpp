#include "OsuOptionsMenu.h"

#include "Engine.h"
#include "Environment.h"
#include "ConVar.h"
#include "ResourceManager.h"
#include "Sound.h"
#include "SoundEngine.h"
#include "CBaseUICheckbox.h"
#include "CBaseUITextbox.h"
#include "CBaseUILabel.h"
#include "CBaseUIScrollView.h"
#include "CBaseUIContainer.h"
#include "Osu.h"
#include "OsuUIButton.h"
#include "OsuUIContextMenu.h"
#include <algorithm>
#include <cctype>

static const char *timingWidthNames[] = {"Fixed milliseconds", "Map-relative fraction", "Adaptive spread"};

void OsuOptionsMenu::addTimingAudioOptions()
{
	const size_t firstElement = m_elements.size();
	addSubSection("Timing Audio");
	addLabel("Manual standard circles and slider heads.");
	addLabel("Ctrl+O during play; search Timing Audio to return here.");
	addLabel("Edit settings, then Apply. Mute below acts immediately.");
	addLabel("Ctrl+Enter applies while editing Timing Audio.");
	addLabel("Pause first for longer edits while music is running.");
	addLabel("Closing without Apply discards edits. Use decimal points.");
	m_timingAudioMuteButton = addButton("Mute training cues (keep learning)");
	m_timingAudioMuteButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioMute));
	m_elements.back().searchTags = "timing audio mute";
	m_timingAudioStatus = addLabel("Current game settings.");
	m_elements.back().searchTags = "timing audio status";
	addButton("Apply timing settings to game")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioApply));
	m_elements.back().searchTags = "timing audio apply target gain reference width adaptive half-life startup gate break cue";
	for (const auto &spec : OsuTimingAudioSettings::specs())
	{
		if (std::string(spec.name) == "osu_timing_audio_muted") continue; // immediate button above
		TimingAudioField field = {&spec, NULL, NULL};
		const UString tags = UString::format("timing audio %s", spec.label);
		if (std::string(spec.name) == "osu_timing_audio_deadzone_mode")
		{
			m_timingAudioWidthButton = addButton("Silent width");
			m_timingAudioWidthButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioWidth));
		}
		else if (spec.type == OsuTimingAudioSettings::BOOLEAN)
			field.checkbox = addCheckbox(spec.label, "Changes take effect after Apply.", NULL);
		else
		{
			addLabel(spec.label);
			m_elements.back().searchTags = tags;
			field.textbox = addTextbox("", (ConVar*)NULL);
		}
		m_elements.back().searchTags = tags;
		m_timingAudioFields.push_back(field);
	}
	addLabel("Adaptation, activity and threshold changes restart learning.");
	addLabel("Target, reference, width, gain and cue changes retain it.");
	addLabel("Target: 0 centre; +/-1 at 300, +/-2 at 100, +/-3 at 50.");
	addLabel("Negative target = early. Gate stays at actual map zero.");
	addLabel("Adaptive uses fixed width for its first two eligible hits.");
	addLabel("Same-filename cue edits reload on map retry.");
	addButton("Apply timing settings to game")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioApply));
	m_elements.back().searchTags = "timing audio apply target gain reference width adaptive half-life startup gate break cue";
	addButton("Timing defaults into editor (then Apply)")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioDefaults));
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
	addSubSection("Timing Audio Profiles");
	addLabel("Profiles contain timing settings only, not maps, skin or mix.");
	addLabel("Learned timing is not saved in profiles.");
	addLabel("Apply first; Save captures the settings currently in the game.");
	addLabel("Profile name:");
	m_timingAudioProfileName = addTextbox("", (ConVar*)NULL);
	m_elements.back().searchTags = "timing audio profile name";
	addButton("Save applied settings as named profile")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioSaveProfile));
	m_elements.back().searchTags = "timing audio profile save";
	m_timingAudioLoadButton = addButton("Load and apply saved profile...");
	m_timingAudioLoadButton->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioLoadProfile));
	m_elements.back().searchTags = "timing audio profile load";
	addButton("Delete named profile (confirmation required)")->setClickCallback(fastdelegate::MakeDelegate(this, &OsuOptionsMenu::onTimingAudioDeleteProfile));
	m_elements.back().searchTags = "timing audio profile delete";
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
	int editState = draft != current ? 1 : 0;
	for (const auto &spec : OsuTimingAudioSettings::specs())
		if (spec.restarts && draft.at(spec.name) != current.at(spec.name)) editState = 2;
	if (editState != m_timingAudioEditState)
	{
		m_timingAudioEditState = editState;
		m_timingAudioStatus->setText(editState == 2 ? "Unapplied edits include settings that can restart learning."
			: editState == 1 ? "Unapplied edits. Click Apply to change the game." : "Editor matches current game settings.");
		m_timingAudioStatus->setTextColor(0xffffffff);
	}
	m_timingAudioMuteButton->setText(convar->getConVarByName("osu_timing_audio_muted")->getBool()
		? "Unmute training cues (keep learning)" : "Mute training cues (keep learning)");
	for (const TimingAudioField &field : m_timingAudioFields)
	{
		if (field.textbox == NULL) continue;
		const std::string key = field.spec->name;
		bool enabled = true;
		if (key == "osu_timing_audio_target") enabled = draft.at("osu_timing_audio_recent") == "0";
		if (key == "osu_timing_audio_deadzone") enabled = m_timingAudioWidth != 1;
		if (key == "osu_timing_audio_deadzone_fraction") enabled = m_timingAudioWidth == 1;
		if (key.find("osu_timing_audio_deadzone_adaptive_") == 0) enabled = m_timingAudioWidth == 2;
		if (key == "osu_timing_audio_half_life_seconds") enabled = draft.at("osu_timing_audio_fixed_hits") == "0";
		if (key == "osu_timing_audio_half_life_hits") enabled = draft.at("osu_timing_audio_fixed_hits") == "1";
		field.textbox->setEnabled(enabled);
	}
}

void OsuOptionsMenu::timingAudioStatus(UString text, bool error)
{
	m_timingAudioStatus->setText(text);
	m_timingAudioStatus->setTextColor(error ? 0xffff6666 : 0xffffffff);
	m_osu->getNotificationOverlay()->addNotification(text, error ? 0xffff6666 : 0xffffffff, false, 1.5f);
}

void OsuOptionsMenu::onTimingAudioApply()
{
	m_timingAudioConfirm.clear();
	const std::string error = OsuTimingAudioSettings::apply(timingAudioDraft());
	if (!error.empty()) { timingAudioStatus(error.c_str(), true); return; }
	syncTimingAudio(OsuTimingAudioSettings::capture());
	m_timingAudioConfirm.clear();
	timingAudioStatus("Applied to game. Existing learning/reset rules apply.");
}

void OsuOptionsMenu::onTimingAudioDefaults()
{
	m_timingAudioConfirm.clear();
	syncTimingAudio(OsuTimingAudioSettings::capture(true));
	timingAudioStatus("Defaults in editor; click Apply to use them.");
}

void OsuOptionsMenu::onTimingAudioMute()
{
	m_timingAudioConfirm.clear();
	ConVar *mute = convar->getConVarByName("osu_timing_audio_muted");
	mute->setValue(!mute->getBool());
	timingAudioStatus(mute->getBool() ? "Cues muted. Enabled timing feedback keeps learning." : "Cues unmuted. Cue gain is unchanged.");
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
		timingAudioStatus("Click Save again within 10 seconds to replace this profile."); return;
	}
	profiles[name] = values;
	error = OsuTimingAudioSettings::writeProfiles(profiles);
	m_timingAudioConfirm.clear();
	timingAudioStatus(error.empty() ? UString::format("Saved timing profile: %s", name.c_str()) : UString(error.c_str()), !error.empty());
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
	timingAudioStatus(UString::format("Loaded and applied timing profile: %s", name.toUtf8()));
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
		timingAudioStatus("Click Delete again within 10 seconds to remove this profile."); return;
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
