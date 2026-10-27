-- emoji_prime.lua: pictures over the video as each Japanese word is spoken.
--
-- Plays the overlay built by emoji_prime.py. Looked up, in order:
--   --script-opts=emoji_prime-overlay=/path/to/overlay.json
--   <video dir>/<video stem>.emojiprime/overlay.json
-- Shift+E toggles. Needs mpv 0.33 or newer (overlay-add).

local mp = require "mp"
local utils = require "mp.utils"
local options = require "mp.options"

local opts = { overlay = "" }
options.read_options(opts, "emoji_prime")

local data, img_dir = nil, nil
local enabled = true
local shown = {}   -- overlay id -> true
local shown_key = ""

local function clear()
	for id in pairs(shown) do
		mp.commandv("overlay-remove", id)
	end
	shown, shown_key = {}, ""
end

local function load(path)
	local f = io.open(path, "r")
	if not f then return false end
	local parsed = utils.parse_json(f:read("*a"))
	f:close()
	if not parsed then
		mp.msg.warn("couldn't parse " .. path)
		return false
	end
	data = parsed
	img_dir = utils.split_path(path) .. "img/"
	mp.msg.info(("loaded %d pictures from %s"):format(#data.items, path))
	return true
end

-- each item sits at its own video-relative pos (centre), already tilted and outlined
local function draw(t)
	if not (data and enabled and t) then
		if shown_key ~= "" then clear() end
		return
	end
	local d = mp.get_property_native("osd-dimensions")
	if not d or not d.w or d.w == 0 then return end
	local active, key = {}, {}
	for i, it in ipairs(data.items) do
		if it.start > t then break end
		if t < it["end"] then
			active[#active + 1] = it
			key[#key + 1] = i
		end
	end
	local vw, vh = d.w - d.ml - d.mr, d.h - d.mt - d.mb
	local want, size = data.box * vh, nil
	for _, s in ipairs(data.sizes) do  -- rendered size nearest to box x video height
		if not size or math.abs(s - want) < math.abs(size - want) then size = s end
	end
	size = tostring(size)
	local k = size .. ":" .. d.w .. "x" .. d.h .. ":" .. table.concat(key, ",")
	if k == shown_key then return end
	clear()
	shown_key = k
	for n, it in ipairs(active) do
		if n > 63 then break end
		local w, h, file = it.img[size][1], it.img[size][2], it.img[size][3]
		local x = math.floor(d.ml + it.pos[1] * vw - w / 2)
		local y = math.floor(d.mt + it.pos[2] * vh - h / 2)
		x = math.max(0, math.min(d.w - w, x))
		y = math.max(0, math.min(d.h - h, y))
		mp.commandv("overlay-add", n - 1, x, y, img_dir .. file, 0, "bgra", w, h, w * 4)
		shown[n - 1] = true
	end
end

mp.register_event("file-loaded", function()
	clear()
	data = nil
	if opts.overlay ~= "" and load(opts.overlay) then return end
	local path = mp.get_property("path", "")
	local dir, name = utils.split_path(path)
	local stem = name:gsub("%.[^.]+$", "")
	load(utils.join_path(dir, stem .. ".emojiprime/overlay.json"))
end)

mp.observe_property("time-pos", "number", function(_, t) draw(t) end)
mp.observe_property("osd-dimensions", "native", function()
	shown_key = ""
	draw(mp.get_property_number("time-pos"))
end)

mp.add_key_binding("E", "toggle", function()
	enabled = not enabled
	mp.osd_message("emoji prime: " .. (enabled and "on" or "off"))
	shown_key = ""
	draw(mp.get_property_number("time-pos"))
end)
