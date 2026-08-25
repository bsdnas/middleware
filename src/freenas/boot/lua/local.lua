local config = require("config")
local hook = require("hook")

local function debugModules()
	if config.kernel_loaded == "kernel-debug" then
		config.parse("openzfs_load=NO")
		config.parse("openzfs-debug_load=YES")
	else
		config.parse("openzfs_load=YES")
		config.parse("openzfs-debug_load=NO")
	end
end

hook.register("kernel.loaded", debugModules)

-- Boot report: list every disk the loader managed to enumerate and every pool
-- it assembled from them, then hold the screen long enough to read it or take
-- a photograph.  On an appliance this single screen answers the two questions
-- asked first whenever a machine will not come up: which disks did it see, and
-- which pools came up whole.  "lsdev -v" prints both, and for the zfs device it
-- prints each pool with the state of its vdevs.
--
-- Off unless bsdnas_boot_report="YES" is set in loader.conf, so an ordinary
-- boot is not held up; the network install and disk-boot trees turn it on.
-- The pause is bsdnas_boot_report_delay seconds, 5 by default.
--
-- This file is included after loader.conf has been read and before the menu is
-- drawn, so the report shows the devices the loader actually probed.  It cannot
-- show a failure that happens during probing itself: that output comes earlier
-- and straight from the C code.
local function bootReport()
	if loader.getenv("bsdnas_boot_report") ~= "YES" then
		return
	end

	local delay = tonumber(loader.getenv("bsdnas_boot_report_delay")) or 5

	printc("\nDisks and pools found by the loader:\n")
	loader.perform("lsdev -v")
	printc("\nContinuing in " .. delay .. " seconds...\n")
	loader.delay(delay * 1000 * 1000)
end

bootReport()
