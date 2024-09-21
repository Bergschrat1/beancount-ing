import logging
from pathlib import Path
import yaml
from dataclasses import dataclass

import re
from beancount.core.data import Transaction, Posting

log = logging.getLogger("auto_importer")


class ImportRule:
    def __init__(
        self,
        name: str,
        patterns_payee: list[str],
        patterns_narration: list[str],
        replacement_payee: str,
        replacement_narration: str,
        replacement_posting: str,
    ):
        self.name = name
        self._patterns_payee = self._compile_rules(patterns_payee)
        self._patterns_narration = self._compile_rules(patterns_narration)
        self.replacement_payee = replacement_payee
        self.replacement_narration = replacement_narration
        self.replacement_posting = replacement_posting

    def __repr__(self) -> str:
        return f"Import Rule {self.name!r}, patterns_payee={self._patterns_payee}, patterns_narration={self._patterns_narration}, replacement_payee={self.replacement_payee}, replacement_narration={self.replacement_narration}, posting={self.replacement_posting}"

    def _compile_rules(self, patterns: list[str]) -> list[re.Pattern]:
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def _identify_rule(self, transaction: Transaction) -> bool:
        for p in self._patterns_payee:
            if transaction.payee and p.search(transaction.payee):
                return True
        for p in self._patterns_narration:
            if transaction.narration and p.search(transaction.narration):
                return True
        return False

    def _apply_rule(self, transaction: Transaction) -> Transaction:
        if self.replacement_payee:
            log.debug(f"Replacing payee: {transaction.payee} with {self.replacement_payee}")
            transaction.meta["original_payee"] = transaction.payee
            transaction = transaction._replace(payee=self.replacement_payee)
        if self.replacement_narration:
            log.debug(f"Replacing narration: {transaction.narration} with {self.replacement_narration}")
            transaction.meta["original_narration"] = transaction.narration
            transaction = transaction._replace(narration=self.replacement_narration)
        if self.replacement_posting:
            log.debug(f"Adding posting: {self.replacement_posting}")
            amount = -transaction.postings[0].units
            transaction.postings.append(Posting(self.replacement_posting, amount, None, None, None, None))
        return transaction


class AutoImporter:
    """MixIn that allows to automatically assign payee, narration and postings to transactions."""

    def _load_import_rules(self, filepath: Path) -> list[ImportRule]:
        with open(filepath, "r") as f:
            yaml_content = f.read()
            data = yaml.safe_load(yaml_content)
        rules = []

        for name, details in data.items():
            match = details.get("match", {})
            replacements = details.get("replacements", {})

            rules.append(
                ImportRule(
                    name=name,
                    patterns_narration=match.get("narration", []),
                    patterns_payee=match.get("payee", []),
                    replacement_narration=replacements.get("narration", ""),
                    replacement_payee=replacements.get("payee", ""),
                    replacement_posting=replacements.get("account", ""),
                )
            )

        return rules

    def _auto_fill_transaction(self, transaction: Transaction, rules: list[ImportRule]) -> Transaction:
        fixed_transaction = transaction
        for r in rules:
            if r._identify_rule(transaction):
                fixed_transaction = r._apply_rule(transaction)
        return fixed_transaction
