from pathlib import Path
import yaml
from dataclasses import dataclass

@dataclass
class ImportRule:
    name: str
    match_narration: list[str]
    match_payee: list[str]
    replacement_narration: str
    replacement_account: str
    replacement_payee: str


class AutoImporter:
    """MixIn that allows to automatically assign accounts to transactions."""

    def _load_import_rules(self, filepath: Path) -> list[ImportRule]:
        with open(filepath, "r") as f:
            yaml_content = f.read()
            data = yaml.safe_load(yaml_content)
        rules = []
    
        for name, details in data.items():
            match = details.get('match', {})
            replacements = details.get('replacements', {})
        
            rules.append(ImportRule(
                name=name,
                match_narration=match.get('narration', []),
                match_payee=match.get('payee', []),
                replacement_narration=replacements.get('narration', ''),
                replacement_account=replacements.get('account', ''),
                replacement_payee=replacements.get('payee', '')
            ))
    
        return rules

    def _fix_entry(self, entry, replacements):
        payee, description, posting = replacements
        if payee:
            log.debug(f"Replacing payee: {entry.payee} with {payee}")
            entry.meta["original_payee"] = entry.payee
            entry = entry._replace(payee=payee)
        if description:
            log.debug(f"Replacing description: {entry.narration} with {description}")
            entry.meta["original_narration"] = entry.narration
            entry = entry._replace(narration=description)
        if posting:
            log.debug(f"Adding posting: {posting}")
            amount = -entry.postings[0].units
            entry.postings.append(data.Posting(posting, amount, None, None, None, None))
        # TODO mark transaction to know that it was changed
        return entry

    def _get_fixed_entry(self, entry, rules):
        log.debug("Matching rules for entry " + str(entry))
        for rule in rules:
            # match payee
            for pattern in rule.payee_regexs:
                log.debug("Matching payee regex " + str(pattern.pattern) + " on string " + str(entry.payee))
                if entry.payee and pattern.search(entry.payee):
                    log.debug("Found a matching payee.")
                    fixed_entry = self._fix_entry(entry, rule[0])
                    return fixed_entry
                else:
                    log.debug("no match")
            # match description
            for pattern in rule.description_regexs:
                log.debug("Matching description regex " + str(pattern.pattern) + " on string " + str(entry.narration))
                if entry.narration and pattern.search(entry.narration):
                    log.debug("Found a matching description.")
                    fixed_entry = self._fix_entry(entry, rule[0])
                    return fixed_entry
                else:
                    log.debug("no match")
        return entry

    def _compile_import_rules(self, rules):
        comp_import_rules = []
        for rule in rules:
            if len(rule) != 3:
                raise (ValueError(f"Invalid rule configuration: {rule}"))
            compiled_rule = import_rule(
                (rule[0]),
                tuple((re.compile(r, re.IGNORECASE) for r in rule[1])),
                tuple((re.compile(r, re.IGNORECASE) for r in rule[2])),
            )
            comp_import_rules.append(compiled_rule)
        return comp_import_rules
