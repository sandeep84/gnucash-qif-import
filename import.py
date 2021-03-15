#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
GnuCash Python helper script to import transactions from QIF text files into GnuCash's own file format.

https://github.com/hjacobs/gnucash-qif-import
'''

import argparse
import datetime
import json
import logging
import os
import re
import subprocess
import tempfile
import qif

import piecash

def readrules(filename):
    '''Read the rules file.
    Populate an list with results. The list contents are:
    ([pattern], [account name]), ([pattern], [account name]) ...
    Note, this is in reverse order from the file.
    '''
    rules = []

    if filename is not None:
        with open(filename, 'r') as fd:
            for line in fd:
                line = line.strip()
                if line and not line.startswith('#'):
                    result = re.match(r"^(.+);(.+)", line)
                    if result:
                        ac = result.group(1)
                        pattern = result.group(2)
                        compiled = re.compile(pattern)  # Makesure RE is OK
                        rules.append((compiled, ac))
                    else:
                        logging.warn('Ignoring line: (incorrect format): "%s"', line)

    return rules

def read_entries(fn, imported, default_account):
    base = os.path.basename(fn)
    if base in imported:
        logging.info('Skipping %s (already imported)', base)
        return []

    logging.debug('Reading %s..', fn)
    with open(fn) as fd:
        if fn.endswith('.csv'):
            items = qif.parse_csv(fd)
        elif fn.endswith('.qif'):
            items = qif.parse_qif(fd)

    for item in items:
        if item.account is None:
            item.account = default_account
        if item.split_amount is None:
            item.split_amount = item.amount

    imported.add(fn)
    logging.debug('Read %s items from %s', len(items), fn)
    return items

def get_ac_from_str(search_str, rules, book=None, split_account=None):
    for pattern, acpath in rules:
        if pattern.search(search_str):
            return acpath
    
    if book is not None:
        split_acc = book.accounts(fullname=split_account)
        return "Imbalance-" + split_acc.commodity.mnemonic

def getCategory(book, item, rules):
    return get_ac_from_str(item.payee, rules, book, item.account)

def add_transaction(book, acc, acc_splits, item, currency, rules, dry_run):
    if item.split_category is None:
        item.split_category = getCategory(book, item, rules)
    if item.split_category == "IGNORE":
        logging.debug('Skipping entry %s (%s)', item.date.strftime('%Y-%m-%d'), item.split_amount)
        return

    acc2 = book.accounts(fullname=item.split_category)
    amount = item.split_amount
    today = datetime.datetime.now()

    for split in acc_splits:
        if split.transaction.description == item.payee and split.transaction.post_date == item.date.date() and split.value == amount:
            logging.debug("    - Skipping since transaction aready exists...")
            return

    logging.info('Adding transaction for account "%s" (%s %s %s %s)..', item.account, item.date.date(), item.payee, item.split_amount,
                 currency.mnemonic)

    if not dry_run:
        tx = piecash.Transaction(
                post_date=item.date.date(),
                enter_date=today,
                currency=currency,
                description = item.payee,
                splits = [
                    piecash.Split(account=acc,  value=amount),
                    piecash.Split(account=acc2, value=-amount),
                ])

def write_transactions_to_gnucash(gnucash_file, currency, all_items, default_account, rules, dry_run=False):
    logging.debug('Opening GnuCash file %s..', gnucash_file)
    book = piecash.open_book(gnucash_file, readonly=False)
    acc = book.accounts(fullname=default_account)
    currency = book.currencies(mnemonic=currency)

    try:
        for item in all_items:
            add_transaction(book, acc, acc.splits, item, currency, rules, dry_run)
        book.flush()

    finally:
        if dry_run:
            logging.debug('** DRY-RUN **')
        else:
            logging.debug('Saving GnuCash file..')
            book.save()


def main(args):
    if args.verbose:
        lvl = logging.DEBUG
    elif args.quiet:
        lvl = logging.WARN
    else:
        lvl = logging.INFO

    logging.basicConfig(level=lvl)

    imported_cache = os.path.expanduser('~/.gnucash-qif-import-cache.json')
    if os.path.exists(imported_cache):
        with open(imported_cache) as fd:
            imported = set(json.load(fd))
    else:
        imported = set()

    rules = readrules(args.rulesfile)

    for fn in args.file:
        print("Processing file: " + fn)
        default_account = args.default_account
        if default_account is None:
            default_account = get_ac_from_str(fn, rules)
            print("Setting default import account to " + default_account)

        all_items = read_entries(fn, imported, default_account)
        write_transactions_to_gnucash(args.gnucash_file, args.currency, all_items, default_account, rules, dry_run=args.dry_run)

    if not args.dry_run:
        with open(imported_cache, 'w') as fd:
            json.dump(list(imported), fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', help='Verbose (debug) logging', action='store_true')
    parser.add_argument('-q', '--quiet', help='Silent mode, only log warnings', action='store_true')
    parser.add_argument('--dry-run', help='Noop, do not write anything', action='store_true')
    parser.add_argument('-c', '--currency', metavar='ISOCODE', help='Currency ISO code (default: GBP)', default='GBP')
    parser.add_argument('-a', '--default-account', help='Gnucash default account')
    parser.add_argument('-f', '--gnucash-file', help='Gnucash data file', default="HomeAccounts.gnucash")
    parser.add_argument("-r", "--rulesfile", help="Rules file", default="rules.txt")
    parser.add_argument('file', nargs='+',
                        help='Input QIF file(s)')

    args = parser.parse_args()
    main(args)

