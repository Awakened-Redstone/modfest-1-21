#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

import common
from assemble_packwiz import SubmissionLockfileFormat
from common import Ansi


def main():
	modrinth_api = "https://api.modrinth.com/v2"
	repo_root = common.get_repo_root()
	constants_file = repo_root / "constants.jsonc"
	submissions_file = repo_root / "submissions.json"
	submission_lock_file = repo_root / "submissions-lock.json"
	packwiz_pack_toml = repo_root / "pack" / "pack.toml"
	packwiz = common.check_packwiz()

	common.fix_packwiz_pack(packwiz_pack_toml)

	constants = common.jsonc_at_home(common.read_file(constants_file))

	# Download the json
	event_name = constants["event"]
	if event_name == None:
		print(f"{Ansi.WARN}No event name defined. Treating it as if there were zero submissions{Ansi.RESET}")
		print(f"Was this unintentional? Check {constants_file.relative_to(repo_root)} and make sure it defines \"event\"")
		submission_data = []
	else:
		submissions_url = f"https://platform.modfest.net/event/{event_name}/submissions"
		with urllib.request.urlopen(submissions_url) as submissions:
			submission_data = json.load(submissions)

	# Update the lock file
	# Read the needed files and transform the submission data into a dict where the ids are keys
	lock_data: SubmissionLockfileFormat = json.loads(common.read_file(submission_lock_file)) if submission_lock_file.exists() else {}
	submissions_by_id = {s["id"]: s for s in submission_data}

	# Remove stale data
	lock_data = {k: v for k, v in lock_data.items() if (k in submissions_by_id)}

	# Loop through all submissions
	rate_limit = common.Ratelimiter(1)
	for mod_id in submissions_by_id:
		platform_info = submissions_by_id[mod_id]
		lock_info = lock_data.get(mod_id)  # Might be None
		# If the url changes we need to update the lock data. This is the only use of 'url' in the lock file
		if lock_info is None or lock_info["url"] != platform_info["download"]:
			print(f"Updating lock data for {mod_id}")
			lock_info = {}  # Reset the lock info for this mod
			assert lock_info is not None  # mypy is quite stupid
			lock_info["url"] = platform_info["download"]

			old_dir = os.getcwd()

			# We steal packwiz's dependency resolution by making a quick packwiz dir
			with tempfile.TemporaryDirectory() as tmpdir_name:
				tmpdir = Path(tmpdir_name)
				# Run commands in the temporary directory

				os.chdir(tmpdir)

				# This is the minimum for packwiz to consider this a pack dir
				shutil.copyfile(packwiz_pack_toml, tmpdir / "pack.toml")
				(tmpdir / "index.toml").touch()

				# Install the mod into the temporary packwiz pack
				rate_limit.limit()
				mod_type = platform_info.get("platform")
				if mod_type != None and mod_type.get("type") == "modrinth":
					subprocess.run([packwiz, "modrinth", "install", "--project-id", mod_type["project_id"], "--version-id", mod_type["version_id"], "-y"])
				else:
					subprocess.run([packwiz, "url", "add", platform_info["download"]])

				# Now lets see which files packwiz thought we should download
				files = {}
				mod_dir = tmpdir / "mods"
				if not mod_dir.exists():
					print(f"{Ansi.WARN}Packwiz didn't generate any files for {mod_id}{Ansi.RESET}")
					continue
				for packwiz_meta in os.listdir(mod_dir):
					packwiz_data = tomllib.loads(common.read_file(mod_dir / packwiz_meta))
					del packwiz_data["update"]
					files[packwiz_meta] = packwiz_data
				lock_info["files"] = files

				os.chdir(old_dir)
		lock_data[mod_id] = lock_info

	# Write the update lock data back
	with open(submission_lock_file, "w") as f:
		f.write(json.dumps(lock_data, indent='\t', sort_keys=True))

	# Make it clear that this script didn't really do anything if event_name is null
	if event_name == None:
		sys.exit(1)


if __name__ == "__main__":
	main()
