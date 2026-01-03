#! /usr/bin/env python3

import argparse
import datetime
import glob
import json
import os
import pickle
import re
import sys

from collections import OrderedDict
from configparser import ConfigParser
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

from compare_locales.compare import compareProjects
from compare_locales.paths import ConfigNotFound, TOMLParser
from fluent.syntax import parse, visitor
from fluent.syntax.serializer import FluentSerializer


# Define the root directory relative to the script location
ROOT_DIR = Path(__file__).resolve().parent.parent


@contextmanager
def execution_lock(lock_file: Path):
    """Ensures a lock file exists during execution and is cleaned up after."""
    if lock_file.exists():
        sys.exit("Checks are already running.")
    try:
        lock_file.touch()
        yield
    finally:
        if lock_file.exists():
            lock_file.unlink()


def load_config(config_path: Path):
    """Loads and validates the configuration file."""
    if not config_path.is_file():
        return None

    config = ConfigParser()
    config.read(config_path)

    try:
        return {
            "tmx_path": Path(config.get("config", "tmx_path")),
            "firefoxl10n_path": Path(config.get("config", "firefoxl10n_path")),
            "toml_path": Path(config.get("config", "toml_path")),
        }
    except Exception as e:
        sys.exit(f"Configuration error: {e}")


class APIChecker:
    def __init__(self, api_url, root_folder, verbose=False):
        self.api_url = api_url
        self.root_folder = Path(root_folder)
        self.verbose = verbose
        self.url_template = "{}/entity/gecko_strings/?id={}:{}"

    def get_json_data(self, url, search_id):
        """Fetches JSON with 5 retries and ensures socket closure."""
        for _ in range(5):
            try:
                with urlopen(url, timeout=10) as response:
                    return json.load(response), True
            except Exception:
                continue
        return {}, False

    def run(self, json_files, locales, plural_forms, results_container):
        for json_file in json_files:
            total_errors = 0
            if self.verbose:
                print(f"CHECK: {json_file}")

            # Load check definitions
            check_path = self.root_folder / "checks" / f"{json_file}.json"
            try:
                with open(check_path, encoding="utf-8") as f:
                    checks = json.load(f)
            except Exception as e:
                print(f"Error loading JSON file {json_file}: {e}")
                continue

            for c in checks:
                query_url = self.url_template.format(
                    self.api_url, c["file"], c["entity"]
                )
                json_data, success = self.get_json_data(
                    query_url, f"{c['file']}:{c['entity']}"
                )

                if not success:
                    results_container.general_errors.append(
                        f"Error checking {c['file']}:{c['entity']}"
                    )
                    continue

                for locale, translation in json_data.items():
                    if locale == "en-US" or locale not in locales:
                        continue

                    # Original Exclusion Logic
                    if "excluded_locales" in c and locale in c["excluded_locales"]:
                        continue
                    if "included_locales" in c and locale not in c["included_locales"]:
                        continue

                    error_msg = self._perform_checks(
                        c, translation, locale, plural_forms
                    )

                    if error_msg:
                        results_container.error_messages[locale].extend(error_msg)
                        total_errors += len(error_msg)

            if total_errors:
                results_container.error_summary[json_file] = total_errors

    def _perform_checks(self, c, translation, locale, plural_forms):
        error_msg = []
        check_type = c["type"]
        file_entity = f"({c['file']}:{c['entity']})"

        if check_type == "include_regex":
            for t in c["checks"]:
                if not re.search(t, translation, re.UNICODE):
                    error_msg.append(f"Missing {t} {file_entity}")

        elif check_type == "not_include_regex":
            for t in c["checks"]:
                if re.search(t, translation, re.UNICODE):
                    error_msg.append(f"String includes {t} {file_entity}")

        elif check_type == "include":
            for t in c["checks"]:
                if t not in translation:
                    error_msg.append(f"Missing {t} {file_entity}")

        elif check_type == "not_include":
            for t in c["checks"]:
                if t in translation:
                    error_msg.append(f"Not expected text {t} {file_entity}")

        elif check_type == "equal_to":
            if c["value"].lower() != translation.lower():
                error_msg.append(
                    f"{translation} is not equal to {c['value']} {file_entity}"
                )

        elif check_type == "not_equal_to":
            if c["value"] == translation:
                error_msg.append(
                    f"{translation} is equal to {c['value']} {file_entity}"
                )

        elif check_type == "acceptable_values":
            if translation not in c["values"]:
                error_msg.append(
                    f"{translation} is not an acceptable value {file_entity}"
                )

        elif check_type == "typeof":
            # Note: This check in the original code compared type(str) to a value in JSON.
            if str(type(translation)) != str(c["value"]):
                error_msg.append(
                    f"{translation} is not of type {c['type']} {file_entity}"
                )

        elif check_type == "bytes_length":
            current_length = len(translation.encode("utf-8"))
            if current_length > c["value"]:
                error_msg.append(
                    f"String longer than {c['value']} bytes. Current length: {current_length} bytes. {file_entity}"
                )

        elif check_type == "plural_forms":
            num_forms = len(translation.split(";"))
            if num_forms != plural_forms.get(locale):
                error_msg.append(
                    f"String has {num_forms} plural forms, requested: {plural_forms.get(locale)} {file_entity}"
                )

        return error_msg


class CompareLocalesChecker:
    def __init__(self, firefoxl10n_path, toml_path, locales, verbose=False):
        self.firefoxl10n_path = firefoxl10n_path
        self.toml_path = toml_path
        self.verbose = verbose
        if locales:
            self.locales = tuple(locales)
        else:
            self.locales = [
                loc
                for loc in next(os.walk(self.firefoxl10n_path))[1]
                if not loc.startswith(".")
            ]
            self.locales.sort()

    def _extract_messages(self, data, cl_output):
        """Recursively traverse results to extract warnings and errors."""
        for node_data in data.values() if isinstance(data, dict) else []:
            if isinstance(node_data, list):
                for line in node_data:
                    # Strip line/column numbers for more stable comparison
                    if "warning" in line:
                        msg = re.sub(
                            r" at line [\d]+, column [\d]+", "", line["warning"]
                        )
                        cl_output["warnings"].append(msg)
                    if "error" in line:
                        msg = re.sub(r" at line [\d]+, column [\d]+", "", line["error"])
                        cl_output["errors"].append(msg)
            else:
                self._extract_messages(node_data, cl_output)

    def run(self, results_container):
        """Executes compare-locales and populates the results container."""
        config_env = {"l10n_base": self.firefoxl10n_path}
        try:
            config = TOMLParser().parse(self.toml_path, env=config_env)
            if self.verbose:
                print("Running compare-locales checks...")
            observers = compareProjects([config], self.locales, self.firefoxl10n_path)
        except (ConfigNotFound, OSError) as e:
            sys.exit(f"Error running compare-locales: {e}")

        data = [observer.toJSON() for observer in observers]
        if not data:
            return

        total_errors = 0
        total_warnings = 0

        # Mapping to handle complex keys like 'it/browser'
        details_keys = list(data[0]["details"].keys())
        keys_mapping = {
            k.split(os.path.sep)[0]: k for k in details_keys if os.path.sep in k
        }

        for locale, stats in data[0]["summary"].items():
            if stats["errors"] + stats["warnings"] == 0:
                continue

            cl_output = {"errors": [], "warnings": []}
            locale_key = keys_mapping.get(locale, locale)

            # Use the extracted recursion logic
            cl_data = data[0]["details"].get(locale_key, {})
            self._extract_messages(cl_data, cl_output)

            if stats["errors"] > 0:
                results_container.output_cl["errors"][locale] = cl_output["errors"]
                total_errors += stats["errors"]
            if stats["warnings"] > 0:
                results_container.output_cl["warnings"][locale] = cl_output["warnings"]
                total_warnings += stats["warnings"]

        results_container.error_summary["compare-locales"] = {
            "errors": total_errors,
            "warnings": total_warnings,
        }


class TMXChecker:
    def __init__(
        self,
        tmx_path: str,
        root_folder: str,
        excluded_products: tuple,
        verbose: bool = False,
    ):
        self.tmx_path = Path(tmx_path)
        self.root_folder = Path(root_folder)
        self.excluded_products = excluded_products
        self.verbose = verbose

        self.datal10n_pattern = re.compile(
            r'data-l10n-name\s*=\s*"([a-zA-Z\-]*)"', re.UNICODE
        )
        self.placeable_pattern = re.compile(
            r'(?<!\{)\{\s*([\$|-]?[\w.-]+)(?:[\[(]?[\w.\-, :"]+[\])])*\s*\}', re.UNICODE
        )
        self.fluent_function_pattern = re.compile(
            r"(NUMBER|DATETIME)\(([^)]*)\)", re.UNICODE
        )
        self.css_pattern = re.compile(r"[^\d]*", re.UNICODE)

    def load_exclusions(self):
        """Loads TMX-specific exclusions from JSON."""
        exclusions_file = self.root_folder / "exceptions" / "exclusions_tmx.json"
        with open(exclusions_file, encoding="utf-8") as f:
            return json.load(f)

    def _ignore_string(
        self, string_id, locale, locale_data, exclusions, exclusion_type
    ):
        if string_id not in locale_data:
            return True
        if string_id.startswith(self.excluded_products):
            return True
        if (
            "files" in exclusions[exclusion_type]
            and string_id.split(":")[0] in exclusions[exclusion_type]["files"]
        ):
            return True
        if string_id in exclusions[exclusion_type]["strings"]:
            return True
        if (
            locale in exclusions[exclusion_type]["locales"]
            and string_id in exclusions[exclusion_type]["locales"][locale]
        ):
            return True
        return False

    def _extract_function_calls(self, text):
        """Extracts Fluent function calls (NUMBER, DATETIME)."""
        calls = []
        for m in self.fluent_function_pattern.finditer(text):
            fn = m.group(1)
            params = sorted([p.strip() for p in m.group(2).split(",")])
            call = [fn] + params
            if call not in calls:
                calls.append(call)
        return sorted(calls)

    def preprocess_reference(self, reference_data):
        """Processes en-US data once to identify HTML, CSS, and Fluent functions."""
        processed = {
            "ftl_ids": [],
            "data_l10n_ids": {},
            "fluent_function_ids": {},
            "css_strings": {},
            "html_strings": {},
            "reference_ids": [],
        }

        from custom_html_parser import MyHTMLParser

        html_parser = MyHTMLParser()
        flattener = flattenSelectExpression()
        serializer = FluentSerializer()

        for string_id, text in reference_data.items():
            file_id, message_id = string_id.split(":")

            if "region.properties" in string_id or string_id.startswith(
                self.excluded_products
            ):
                continue

            processed["reference_ids"].append(string_id)

            if file_id.endswith(".ftl"):
                processed["ftl_ids"].append(string_id)

                # Data-l10n-name check
                matches = list(set(self.datal10n_pattern.findall(text)))
                if matches:
                    processed["data_l10n_ids"][string_id] = sorted(matches)

                # CSS check
                if message_id.endswith(".style"):
                    matches = [
                        m
                        for m in self.css_pattern.findall(text.rstrip(";"))
                        if m not in ["", "."]
                    ]
                    processed["css_strings"][string_id] = matches

                # Fluent functions
                fn_matches = self._extract_function_calls(text)
                if fn_matches:
                    processed["fluent_function_ids"][string_id] = fn_matches

            # HTML Tags check
            temp_text = text
            if "*[" in text:
                temp_text = serializer.serialize(
                    flattener.visit(parse(f"temp_id = {text}"))
                )

            cleaned_text = self.placeable_pattern.sub("", temp_text)
            html_parser.clear()
            html_parser.feed(cleaned_text)
            tags = html_parser.get_tags()
            if tags:
                processed["html_strings"][string_id] = tags

        return processed

    def run(self, locales, results_container):
        """Main execution loop for TMX checks."""
        exclusions = self.load_exclusions()
        ref_path = self.tmx_path / "en-US" / "cache_en-US_gecko_strings.json"

        with open(ref_path, encoding="utf-8") as f:
            reference_data = json.load(f)

        ref = self.preprocess_reference(reference_data)
        tmx_errors = 0

        flattener = flattenSelectExpression()
        serializer = FluentSerializer()

        for locale in locales:
            locale_file = self.tmx_path / locale / f"cache_{locale}_gecko_strings.json"
            if not locale_file.exists():
                continue

            with open(locale_file, encoding="utf-8") as f:
                locale_data = json.load(f)

            locale_errors = []

            # Check for mandatory strings
            for sid in exclusions["mandatory"]["strings"]:
                if sid not in locale_data:
                    locale_errors.append(
                        f"Missing translation for mandatory key ({sid})"
                    )

            # General checks (links and pilcrows)
            for sid in ref["reference_ids"]:
                if self._ignore_string(sid, locale, locale_data, exclusions, "ignore"):
                    continue

                translation = locale_data[sid]
                if not self._ignore_string(
                    sid, locale, locale_data, exclusions, "http"
                ):
                    if re.search(r"http(s)*:\/\/", translation, re.UNICODE):
                        locale_errors.append(f"Link in string ({sid})")

                if "¶" in translation:
                    locale_errors.append(f"Pilcrow character in string ({sid})")

            # HTML mismatch check
            from custom_html_parser import MyHTMLParser

            lp = MyHTMLParser()
            for sid, ref_tags in ref["html_strings"].items():
                if self._ignore_string(sid, locale, locale_data, exclusions, "HTML"):
                    continue

                trans = locale_data[sid]
                if "*[" in trans:
                    trans = serializer.serialize(
                        flattener.visit(parse(f"temp_id = {trans}"))
                    )

                lp.clear()
                lp.feed(self.placeable_pattern.sub("", trans))
                tags = lp.get_tags()

                if tags != ref_tags and sorted(tags) != sorted(ref_tags):
                    locale_errors.append(f"Mismatched HTML elements in string ({sid})")

            # FTL specific checks (literals, XML entities, printf, string ID)
            for sid in ref["ftl_ids"]:
                if self._ignore_string(sid, locale, locale_data, exclusions, "ignore"):
                    continue

                trans = locale_data[sid]
                if '{ "' in trans and not self._ignore_string(
                    sid, locale, locale_data, exclusions, "ftl_literals"
                ):
                    locale_errors.append(f"Fluent literal in string ({sid})")

                if (
                    re.search(r"&.*;", trans, re.UNICODE)
                    and sid not in exclusions["xml"]["strings"]
                ):
                    locale_errors.append(f"XML entity in Fluent string ({sid})")

                if sid not in exclusions["printf"]["strings"]:
                    if re.search(
                        r"(%(?:[0-9]+\$){0,1}(?:[0-9].){0,1}([sS]))", trans, re.UNICODE
                    ):
                        locale_errors.append(
                            f"printf variables in Fluent string ({sid})"
                        )

                msg_id = sid.split(":")[1]
                if re.search(re.escape(msg_id) + r"\s*=", trans, re.UNICODE):
                    locale_errors.append(
                        f"Message ID is repeated in the Fluent string ({sid})"
                    )

            # data-l10n-name mismatch
            for sid, groups in ref["data_l10n_ids"].items():
                if sid not in locale_data:
                    continue
                m = sorted(list(set(self.datal10n_pattern.findall(locale_data[sid]))))
                if not m:
                    locale_errors.append(
                        f"data-l10n-name missing in Fluent string ({sid})"
                    )
                elif m != groups:
                    locale_errors.append(
                        f"data-l10n-name mismatch in Fluent string ({sid})"
                    )

            # Fluent function mismatch
            for sid, source_matches in ref["fluent_function_ids"].items():
                if self._ignore_string(
                    sid, locale, locale_data, exclusions, "fluent_functions"
                ):
                    continue
                m = self._extract_function_calls(locale_data[sid])
                if not m:
                    locale_errors.append(
                        f"Fluent function missing in Fluent string ({sid})"
                    )
                elif m != source_matches:
                    locale_errors.append(
                        f"Fluent function mismatch in Fluent string ({sid})"
                    )

            # CSS mismatch
            for sid, source_css in ref["css_strings"].items():
                if sid not in locale_data:
                    continue
                m = [
                    c
                    for c in self.css_pattern.findall(locale_data[sid].rstrip(";"))
                    if c not in ["", "."]
                ]
                if m != source_css:
                    locale_errors.append(f"CSS mismatch in Fluent string ({sid})")

            if locale_errors:
                results_container.error_messages[locale].extend(locale_errors)
                tmx_errors += len(locale_errors)

        results_container.error_summary["TMX checks"] = tmx_errors


class ResultsArchiver:
    def __init__(self, root_folder: Path, output_path: str):
        self.root_folder = root_folder
        self.output_path = Path(output_path) if output_path else None
        self.pickle_file = self.root_folder / "previous_errors.dump"

    def _diff(self, a, b):
        b_set = set(b)
        return [item for item in a if item not in b_set]

    def _find_differences(self, check_type, current, previous, output):
        """Identifies and prints new vs fixed errors."""
        changes = False
        new = self._diff(current, previous)
        if new:
            changes = True
            output["new"] += new
            print(f"New {check_type} ({len(new)}):")
            print("\n".join(new))

        fixed = self._diff(previous, current)
        if fixed:
            changes = True
            output["fixed"] += fixed
            print(f"Fixed {check_type} ({len(fixed)}):")
            print("\n".join(fixed))

        if changes:
            output["message"].append(f"Total {check_type}: {len(current)}")

        return changes

    def archive(self, current_error_messages, output_cl, error_summary):
        """Orchestrates the comparison and storage logic."""
        # Load previous errors
        previous_errors = {"errors": [], "compare-locales": [], "summary": {}}
        if self.pickle_file.exists():
            try:
                with open(self.pickle_file, "rb") as f:
                    previous_errors = pickle.load(f)
            except Exception as e:
                print(f"Error loading pickle: {e}")

        # Flatten current errors for comparison
        current_errors = []
        for locale, errors in current_error_messages.items():
            for e in errors:
                current_errors.append(f"{locale} - {e}")
        current_errors.sort()

        flattened_cl = []
        for locale, warnings in output_cl["warnings"].items():
            for w in warnings:
                flattened_cl.append(f"{locale} (compare-locales warning): {w}")
        for locale, errors in output_cl["errors"].items():
            for e in errors:
                flattened_cl.append(f"{locale} (compare-locales error): {e}")
        flattened_cl.sort()

        # Prepare output structure
        output = {"new": [], "fixed": [], "message": []}

        changes = self._find_differences(
            "errors", current_errors, previous_errors["errors"], output
        )
        changes_cl = self._find_differences(
            "compare-locale errors",
            flattened_cl,
            previous_errors.get("compare-locales", []),
            output,
        )

        if not changes and not changes_cl:
            print("No changes.")
            if self.output_path:
                output["message"].append(f"No changes ({len(current_errors)}).")

        # Persistence logic
        output_data = {
            "errors": current_errors,
            "compare-locales": flattened_cl,
            "summary": error_summary,
        }

        # Write Pickle for next run
        with open(self.pickle_file, "wb") as f:
            pickle.dump(output_data, f)

        # Handle JSON exports if output_path is provided
        if self.output_path:
            self._save_json_results(output, output_data)

    def _save_json_results(self, diff_output, current_data):
        """Saves checks.json and errors.json."""
        if self.output_path is None:
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        # Clean up output dictionary
        for key in ["new", "fixed"]:
            if not diff_output[key]:
                del diff_output[key]
        if diff_output["message"]:
            diff_output["message"] = "\n".join(diff_output["message"])

        # Update checks.json (historical archive)
        archive_file = self.output_path / "checks.json"
        archive_data = {}
        if archive_file.exists():
            try:
                with open(archive_file) as f:
                    archive_data = json.load(f)
            except Exception:
                pass

        archive_data[timestamp] = diff_output
        with open(archive_file, "w") as f:
            json.dump(archive_data, f, sort_keys=True, indent=2)

        # Update errors.json (current snapshot)
        errors_file = self.output_path / "errors.json"
        with open(errors_file, "w") as f:
            json.dump(current_data, f, sort_keys=True, indent=2)


class flattenSelectExpression(visitor.Transformer):
    def visit_SelectExpression(self, node):
        for variant in node.variants:
            if variant.default:
                default_variant = variant
                break

        node.variants = [default_variant]

        return node


class QualityCheck:
    excluded_products = (
        "calendar",
        "chat",
        "editor",
        "extensions",
        "mail",
        "other-licenses",
        "suite",
    )

    def __init__(
        self,
        root_folder,
        tmx_path,
        firefoxl10n_path,
        toml_path,
        requested_check,
        cli_options,
        output_path,
    ):
        """Initialize object"""
        self.root_folder = root_folder
        self.tmx_path = tmx_path
        self.firefoxl10n_path = firefoxl10n_path
        self.toml_path = toml_path
        self.requested_check = requested_check
        self.verbose = cli_options["verbose"]
        self.output_path = output_path
        self.single_locale = cli_options["locale"] is not None

        if self.output_path != "":
            # Read existing content
            self.archive_data = {}
            output_file = os.path.join(output_path, "checks.json")
            if os.path.exists(output_file):
                try:
                    self.archive_data = json.load(open(output_file))
                except Exception as e:
                    print(f"Error loading JSON file {output_file}")
                    print(e)

        self.transvision_url = "https://transvision.flod.org"
        self.api_url = f"{self.transvision_url}/api/v1"

        self.general_errors = []

        start_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"\n--------\nRun: {start_datetime}\n")

        # Create a list of available checks in JSON format
        self.json_files = []
        for check in glob.glob("{}/*.json".format(os.path.join(root_folder, "checks"))):
            check = os.path.basename(check)
            self.json_files.append(os.path.splitext(check)[0])
        self.json_files.sort()

        # Get the list of supported locales
        if cli_options["locale"] is None:
            self.getLocales()
        else:
            self.locales = [cli_options["locale"]]

        # Store the number of plural forms for each locale
        self.plural_forms = {}
        self.getPluralForms()

        # Initialize other error messages
        self.error_messages = OrderedDict()
        self.error_summary = {}
        self.output_cl = {"errors": {}, "warnings": {}}
        for locale in self.locales:
            self.error_messages[locale] = []

        # Run Tranvision checks
        if not cli_options["tmx"]:
            self.check_API()
            if requested_check == "all":
                self.check_view("variables")
                self.check_view("shortcuts")
                self.check_view("empty")

        # Check local TMX for FTL issues if available
        if requested_check == "all" and self.tmx_path != "":
            self.check_TMX()

        # Run compare-locales checks if repos are available
        if (
            not cli_options["ignore_comparelocales"]
            and not cli_options["tmx"]
            and requested_check == "all"
            and self.firefoxl10n_path != ""
        ):
            self.check_repos()

        # Print errors
        if self.verbose:
            self.printErrors()

        # Compare with previous run
        if requested_check == "all":
            self.compare_previous_run()

    def compare_previous_run(self):
        """Compare current results with previous run using ResultsArchiver."""
        archiver = ResultsArchiver(
            root_folder=Path(self.root_folder), output_path=self.output_path
        )
        archiver.archive(
            current_error_messages=self.error_messages,
            output_cl=self.output_cl,
            error_summary=self.error_summary,
        )

    def getJsonData(self, url, search_id):
        """
        Return two values:
        - Array of data
        - If the request succeeded (boolean)
        """
        for try_number in range(5):
            try:
                response = urlopen(url)
                json_data = json.load(response)
                return (json_data, True)
            except Exception:
                # print(f"Error reading URL: {url}")
                continue

        self.general_errors.append(f"Error reading {search_id}")
        return ([], False)

    def getPluralForms(self):
        """Get the number of plural forms for each locale"""

        from compare_locales.plurals import get_plural

        url = f"{self.api_url}/entity/gecko_strings/?id=toolkit/chrome/global/intl.properties:pluralRule"
        if self.verbose:
            print("Reading the list of plural forms")
        locales_plural_rules, success = self.getJsonData(url, "list of plural forms")
        if not success:
            sys.exit("CRITICAL ERROR: List of plural forms not available")

        for locale, rule_number in locales_plural_rules.items():
            num_plurals = get_plural(locale)
            if num_plurals is None:
                # Temporary fix for szl
                if locale == "szl":
                    num_plurals = 3
                else:
                    # Fall back to English
                    num_plurals = 2
            else:
                num_plurals = len(get_plural(locale))
            self.plural_forms[locale] = num_plurals

    def getLocales(self):
        """Get the list of supported locales"""
        if self.verbose:
            print("Reading the list of supported locales")
        url = f"{self.api_url}/locales/gecko_strings/"
        self.locales, success = self.getJsonData(url, "list of supported locales")
        # Remove en-US from locales
        self.locales.remove("en-US")
        if not success:
            sys.exit("CRITICAL ERROR: List of support locales not available")

    def printErrors(self):
        """Print error messages"""
        error_count = 0
        locales_with_errors = OrderedDict()
        for locale, errors in self.error_messages.items():
            if errors:
                num_errors = len(errors)
                print(f"\n----\nLocale: {locale} ({num_errors})")
                locales_with_errors[locale] = num_errors
                error_count += num_errors
                for e in errors:
                    print(f"- {e}")
        if error_count:
            print(f"\n----\nTotal errors: {error_count}")
        else:
            print("\n----\nNo errors")

        if locales_with_errors:
            print(f"\n----\nLocales with errors ({len(locales_with_errors)} locales):")
            for locale, num in locales_with_errors.items():
                print(f"- {locale} ({num})")

        # Error summary
        if self.error_summary:
            print("\n----\nErrors summary by type:")
            for check, count in self.error_summary.items():
                print(f"- {check}: {count}")

        # General error (e.g. invalid API calls)
        if self.general_errors:
            print(f"\n----\nGeneral errors ({len(self.general_errors)} errors):")
            self.general_errors.sort()
            print("\n".join(self.general_errors))

    def sanity_check_JSON(self):
        """Do a sanity check on JSON files, checking for duplicates"""
        for json_file in self.json_files:
            try:
                checks = json.load(
                    open(os.path.join(self.root_folder, "checks", json_file + ".json"))
                )
            except Exception as e:
                print(f"Error loading JSON file {json_file}")
                sys.exit(e)

            available_checks = []
            for c in checks:
                id = f"{c['file']}-{c['entity']}-{c['type']}"
                if id in available_checks:
                    print(f"WARNING: check {id} is duplicated")
                    continue
                available_checks.append(id)

    def check_API(self):
        """Check strings via API requests"""
        self.sanity_check_JSON()

        # Handle single-check requests
        active_files = self.json_files
        if self.requested_check != "all":
            if self.requested_check not in self.json_files:
                sys.exit(
                    f"ERROR: Requested check ({self.requested_check}) does not exist."
                )
            active_files = [self.requested_check]

        # Initialize and run the extracted checker
        checker = APIChecker(
            api_url=self.api_url, root_folder=self.root_folder, verbose=self.verbose
        )

        checker.run(
            json_files=active_files,
            locales=self.locales,
            plural_forms=self.plural_forms,
            results_container=self,
        )

    def check_view(self, check_name: str):
        """
        Check views for access keys, keyboard shortcuts, and empty strings.
        """
        if self.verbose:
            display_names = {
                "variables": "variables",
                "shortcuts": "keyboard shortcuts",
                "empty": "empty strings",
            }
            print(f"CHECK: {display_names.get(check_name, check_name)}")

        # Define API URLs
        url_templates = {
            "variables": "{}/variables/?locale={}&repo=gecko_strings&json",
            "shortcuts": "{}/commandkeys/?locale={}&repo=gecko_strings&json",
            "empty": "{}/empty-strings/?locale={}&json",
        }
        url = url_templates.get(check_name, "")

        # 1. Load Centralized Exceptions from JSON
        exceptions_path = Path(self.root_folder) / "exceptions" / "view_exceptions.json"
        exceptions = {}
        if exceptions_path.exists():
            try:
                with open(exceptions_path, encoding="utf-8") as f:
                    exceptions = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error reading exceptions JSON: {e}")

        total_errors = 0
        for locale in self.locales:
            # Fetch data using the existing getJsonData logic
            errors, success = self.getJsonData(
                url.format(self.transvision_url, locale),
                f"{check_name} for {locale}",
            )

            if not success:
                self.general_errors.append(
                    f"Error checking *{check_name}* for locale {locale}"
                )
                continue

            # Get locale-specific exceptions for this check type
            locale_exceptions = (
                exceptions.get(check_name, {}).get("locales", {}).get(locale, [])
            )

            for error in errors:
                # Ignore excluded products
                if error.startswith(self.excluded_products):
                    continue

                # Ignore general exclusions
                if error in exceptions.get(check_name, {}).get("exclusions", []):
                    continue

                if error in locale_exceptions:
                    continue

                # Maintain original error message format
                # Replaces the first instance of locale with check_name
                error_msg = f"{locale}: {error}".replace(locale, check_name, 1)
                self.error_messages[locale].append(error_msg)
                total_errors += 1

        if total_errors:
            self.error_summary[check_name] = total_errors

    def check_repos(self):
        """Run compare-locales against repos using CompareLocalesChecker."""
        checker = CompareLocalesChecker(
            firefoxl10n_path=self.firefoxl10n_path,
            toml_path=self.toml_path,
            locales=self.locales if self.single_locale else [],
            verbose=self.verbose,
        )
        checker.run(self)

    def check_TMX(self):
        """Check local TMX for issues, mostly on FTL files"""
        if self.verbose:
            print("Running TMX checks...")

        checker = TMXChecker(
            tmx_path=self.tmx_path,
            root_folder=self.root_folder,
            excluded_products=self.excluded_products,
            verbose=self.verbose,
        )
        checker.run(self.locales, self)


def main():
    # Parse command line options
    cl_parser = argparse.ArgumentParser()
    cl_parser.add_argument("check", help="Run a single check", default="all", nargs="?")
    cl_parser.add_argument("--locale", dest="locale", help="Run single locale")
    cl_parser.add_argument("--verbose", dest="verbose", action="store_true")
    cl_parser.add_argument(
        "--tmx", dest="tmx", help="Only check TMX", action="store_true"
    )
    cl_parser.add_argument(
        "--nocl",
        dest="ignore_comparelocales",
        help="Don't run compare-locales checks",
        action="store_true",
    )
    cl_parser.add_argument(
        "--output",
        nargs="?",
        help="Path to folder where to store output in JSON format",
        default="",
    )
    args = cl_parser.parse_args()

    # Check if there's a config file (optional)
    config_path = ROOT_DIR / "config" / "config.ini"
    config_data = load_config(config_path)

    lock_file = ROOT_DIR / ".running"

    # Use context manager to handle the lifecycle of the lock file
    with execution_lock(lock_file):
        cli_options = {
            "verbose": args.verbose,
            "tmx": args.tmx,
            "ignore_comparelocales": args.ignore_comparelocales,
            "locale": args.locale,
        }

        QualityCheck(
            root_folder=str(ROOT_DIR),
            tmx_path=str(config_data["tmx_path"]),
            firefoxl10n_path=str(config_data["firefoxl10n_path"]),
            toml_path=str(config_data["toml_path"]),
            requested_check=args.check,
            cli_options=cli_options,
            output_path=args.output,
        )


if __name__ == "__main__":
    main()
