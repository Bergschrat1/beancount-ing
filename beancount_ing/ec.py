import csv
from datetime import datetime, timedelta
from itertools import count
import re
import warnings
from collections import namedtuple
from typing import Optional
import logging

from beancount.core.amount import Amount
from beancount.core import data, flags
from beancount.core.number import Decimal
from beangulp.importer import Importer


BANKS = ("ING", "ING-DiBa")

META_KEYS = ("IBAN", "Kontoname", "Bank", "Kunde", "Zeitraum", "Saldo")

PRE_HEADER = (
    "In der CSV-Datei finden Sie alle bereits gebuchten Umsätze. "
    "Die vorgemerkten Umsätze werden nicht aufgenommen, auch wenn sie in "
    "Ihrem Internetbanking angezeigt werden."
)

log = logging.getLogger()
#log.setLevel(logging.INFO)

class InvalidFormatError(Exception):
    pass


def _format_iban(iban):
    return re.sub(r"\s+", "", iban, flags=re.UNICODE)


def _format_number_de(value: str) -> Decimal:
    thousands_sep = "."
    decimal_sep = ","

    return Decimal(value.replace(thousands_sep, "").replace(decimal_sep, "."))

import_rule = namedtuple('import_rule',[
    'replacements',
    'payee_regexs',
    'description_regexs',
])

class ECImporter(Importer):
    def __init__(
        self,
        iban: str,
        account_name: str,
        user: str,
        file_encoding: Optional[str] = "ISO-8859-1",
        import_rules=[]
    ):
        self.iban = _format_iban(iban)
        self.account_name = account_name
        self.user = user
        self.file_encoding = file_encoding

        self._date_from = None
        self._date_to = None
        self._line_index = -1
        self.import_rules = import_rules
        log.debug(f"Loaded importer with the folloging rules: {self.import_rules}")

    def account(self, filepath: str) -> data.Account:
        return self.account_name

    def _is_valid_first_header(self, line):
        return line.startswith("Umsatzanzeige;Datei erstellt am")

    def _is_valid_second_header(self, line):
        return line == ";Letztes Update: aktuell"

    def identify(self, filepath: str):
        with open(filepath, encoding=self.file_encoding) as fd:

            def _read_line():
                return fd.readline().strip()

            # Header - first line
            line = _read_line()

            if not self._is_valid_first_header(line):
                return False

            # Header - second line (optional)
            line = _read_line()

            if line:
                if not self._is_valid_second_header(line):
                    return False
                # Empty line
                line = _read_line()

            if line:
                return False

            # Meta
            lines = [_read_line() for _ in range(len(META_KEYS))]

            reader = csv.reader(
                lines, delimiter=";", quoting=csv.QUOTE_MINIMAL, quotechar='"'
            )

            for line in reader:
                key, value, *_ = line

                if key == "IBAN" and _format_iban(value) != self.iban:
                    return False

                if key == "Bank" and value not in BANKS:
                    return False

                if key == "Kunde" and value != self.user:
                    return False

        return True

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
            entry.postings.append(
                data.Posting(posting, amount, None, None, None, None)
            )
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
                raise(ValueError(f"Invalid rule configuration: {rule}"))
            compiled_rule = import_rule(
                (rule[0]),
                tuple((re.compile(r, re.IGNORECASE) for r in rule[1])),
                tuple((re.compile(r, re.IGNORECASE) for r in rule[2])),
            )
            comp_import_rules.append(compiled_rule)
        return comp_import_rules

    def extract(self, filepath: str, existing_entries: Optional[data.Entries] = None):
        entries = []
        self._line_index = 0

        def _read_line():
            line = fd.readline().strip()
            self._line_index += 1

            return line

        def _read_empty_line():
            line = _read_line()

            if line:
                raise InvalidFormatError()

        # pre-compile import rules for performance
        compiled_import_rules = self._compile_import_rules(self.import_rules)

        with open(filepath, encoding=self.file_encoding) as fd:
            # Header - first line
            line = _read_line()

            if not self._is_valid_first_header(line):
                raise InvalidFormatError()

            # Header - second line (optional)
            line = _read_line()

            if line:
                if not self._is_valid_second_header(line):
                    raise InvalidFormatError()

                # Empty line
                _read_empty_line()

            # Meta
            lines = [_read_line() for _ in range(len(META_KEYS))]

            reader = csv.reader(
                lines, delimiter=";", quoting=csv.QUOTE_MINIMAL, quotechar='"'
            )

            for line in reader:
                key, *values = line
                self._line_index += 1

                if key == "IBAN":
                    if _format_iban(values[0]) != self.iban:
                        raise InvalidFormatError()
                elif key == "Bank":
                    if values[0] not in BANKS:
                        raise InvalidFormatError()
                elif key == "Kunde":
                    if values[0] != self.user:
                        raise InvalidFormatError()
                elif key == "Zeitraum":
                    splits = values[0].strip().split(" - ")

                    if len(splits) != 2:
                        raise InvalidFormatError()

                    self._date_from = datetime.strptime(splits[0], "%d.%m.%Y").date()
                    self._date_to = datetime.strptime(splits[1], "%d.%m.%Y").date()
                elif key == "Saldo":
                    # actually this is not a useful balance, because it is
                    # valid on the date of generating the CSV (see first header
                    # line) and not on the closing date of the transactions
                    # (see metadata field 'Zeitraum')
                    pass

            # Empty line
            _read_empty_line()

            # Pre-header line (or optional sorting line)
            line = _read_line()

            descending_by_date = ascending_by_date = None

            if line.startswith("Sortierung"):
                if re.match(".*Datum absteigend", line):
                    descending_by_date = True
                elif re.match(".*Datum aufsteigend", line):
                    ascending_by_date = True
                else:
                    warnings.warn(
                        f"{filepath}:{self._line_index}: "
                        "balance assertions can only be generated "
                        "if transactions are sorted by date"
                    )
                _read_empty_line()

                line = _read_line()

            if line != PRE_HEADER:
                raise InvalidFormatError()

            # Empty line
            _read_empty_line()

            # Data entries
            reader = csv.reader(
                fd, delimiter=";", quoting=csv.QUOTE_MINIMAL, quotechar='"'
            )

            def remap(names):
                # https://stackoverflow.com/a/31771695
                counter = count(1)

                return [
                    "Währung_{}".format(next(counter)) if name == "Währung" else name
                    for name in names
                ]

            field_names = remap(next(reader))

            # memoize first and last transactions for balance assertion
            first_transaction = last_transaction = None

            for row in reader:
                line = dict(zip(field_names, row))

                # Mark first and last transaction together with line numbers
                last_transaction = (self._line_index, line)
                if first_transaction is None:
                    first_transaction = last_transaction
                date = line["Buchung"]
                payee = line["Auftraggeber/Empfänger"]
                booking_text = line["Buchungstext"]
                description = line["Verwendungszweck"]
                amount = line["Betrag"]
                currency = line["Währung_2"]

                meta = data.new_metadata(filepath, self._line_index)

                amount = Amount(_format_number_de(amount), currency)
                date = datetime.strptime(date, "%d.%m.%Y").date()

                description = "{} {}".format(booking_text, description).strip()

                postings = [
                    data.Posting(self.account(filepath), amount, None, None, None, None)
                ]
                entry = data.Transaction(
                        meta,
                        date,
                        flags.FLAG_OKAY,
                        payee,
                        description,
                        data.EMPTY_SET,
                        data.EMPTY_SET,
                        postings,
                )
                fixed_entry = self._get_fixed_entry(entry, compiled_import_rules)

                entries.append(fixed_entry)

                self._line_index += 1

            def balance_assertion(transaction, opening=False, closing=False):
                lineno = transaction[0]
                line = transaction[1]
                balance = _format_number_de(line["Saldo"])

                if opening:
                    # calculate balance before the first transaction
                    # Currencies must match for subtraction
                    if line["Währung_1"] != line["Währung_2"]:
                        warnings.warn(
                            f"{filepath}:{lineno} "
                            "opening balance can not be generated "
                            "due to currency mismatch: "
                            f"{line['Währung_1']} <> {line['Währung_2']}"
                        )
                        return []
                    balance -= _format_number_de(line["Betrag"])
                    balancedate = self._date_from

                if closing:
                    # balance after the last transaction:
                    # next day's opening balance
                    balancedate = self._date_to + timedelta(days=1)

                return [
                    data.Balance(
                        data.new_metadata(filepath, lineno),
                        balancedate,
                        self.account(filepath),
                        Amount(balance, line["Währung_1"]),
                        None,
                        None,
                    )
                ]

            opening_transaction = closing_transaction = None

            # Determine first and last (by date) transactions

            if ascending_by_date:
                opening_transaction = first_transaction
                closing_transaction = last_transaction

            if descending_by_date:
                closing_transaction = first_transaction
                opening_transaction = last_transaction

            if opening_transaction:
                entries.extend(balance_assertion(opening_transaction, opening=True))

            if closing_transaction:
                entries.extend(balance_assertion(closing_transaction, closing=True))

        return entries
