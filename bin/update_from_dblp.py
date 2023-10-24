#!/usr/bin/env python
"""
Import entry from DBLP according to given search input.
"""

import argparse
import logging
import requests
import time
from copy import deepcopy

import bibtex_dblp.config
import bibtex_dblp.database
import bibtex_dblp.dblp_api
import bibtex_dblp.io
from bibtex_dblp.dblp_api import BibFormat


def search_entry(search_string, include_arxiv=False, max_search_results=bibtex_dblp.config.MAX_SEARCH_RESULTS):
    """
    Search an entry for the given search string.
    :param search_string: Search string.
    :param include_arxiv: Whether to include entries from arXiv.
    :param max_search_results: Maximal number of search results to return.
    :return: List of possible entries corresponding to search string, number of total matches
    :raises: HTTPError.
    """
    logging.info("Search: {}".format(search_string))
    search_results = bibtex_dblp.dblp_api.search_publication(search_string, max_search_results=max_search_results)
    if include_arxiv:
        return search_results.results, search_results.total_matches
    else:
        valid_results = []
        total_matches = search_results.total_matches
        for res in search_results.results:
            if "CoRR" in str(res.publication):
                total_matches -= 1
            else:
                valid_results.append(res)
        return valid_results, total_matches


def main():
    parser = argparse.ArgumentParser(description='Update entries in bibliography via DBLP.')

    parser.add_argument('infile', help='Input bibtex file', type=str)
    parser.add_argument('--out', '-o',
                        help='Output bibtex file. If no output file is given, the input file will be overwritten.',
                        type=str, default=None)
    parser.add_argument('--format', '-f', help='DBLP format type to convert into', type=BibFormat,
                        choices=list(BibFormat), default=BibFormat.condensed)
    parser.add_argument('--max-results', help="Maximal number of search results to display.", type=int,
                        default=bibtex_dblp.config.MAX_SEARCH_RESULTS)
    parser.add_argument('--disable-auto', help='Disable automatic selection of publications.', action="store_true")
    parser.add_argument('--include-arxiv', help='Include entries from arXiv in search results.', action="store_true")
    parser.add_argument('--sleep-time', '-t', help='Sleep time (in seconds) between requests. Can prevent errors with too many requests)', type=int, default=3)
    parser.add_argument('--verbose', '-v', help='Print more output', action="store_true")

    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG if args.verbose else logging.INFO)
    outfile = args.infile if args.out is None else args.out
    bib_format = args.format
    max_search_results = args.max_results
    auto_mode = not args.disable_auto
    include_arxiv = args.include_arxiv
    sleep_time = args.sleep_time  # Sleep in seconds if too many requests

    # Load bibliography
    bib = bibtex_dblp.database.load_from_file(args.infile)
    new_entries = deepcopy(bib.entries)
    # Iterate over all entries
    missing_entries = []
    for entry_str, entry in bib.entries.items():
        # Check for id
        dblp_id = bibtex_dblp.dblp_api.extract_dblp_id(entry)
        if dblp_id is not None:
            continue

        if 'author' in entry.persons:
            authors = ", ".join([str(author) for author in entry.persons['author']])
        else:
            authors = ""
        if 'title' in entry.fields:
            title = entry.fields['title']
        else:
            title = ""

        search_string = "{} {}".format(authors, title)
        try:
            search_results, total_matches = search_entry(search_string, include_arxiv=include_arxiv, max_search_results=max_search_results)
            if total_matches == 0:
                # Try once again with only the title
                search_results, total_matches = search_entry(title, include_arxiv=include_arxiv, max_search_results=max_search_results)
        except requests.exceptions.HTTPError as err:
            logging.warning("Search request returned error {}. Skipped this entry.".format(err))
            missing_entries.append(search_string)
            if err.response.status_code == 429:
                time.sleep(sleep_time)  # Sleep again to prevent too many requests
            continue

        if total_matches == 0:
            # No luck -> try next entry
            logging.debug("The search returned no matches.")
            missing_entries.append(search_string)
            time.sleep(sleep_time)  # Prevent too many requests
            continue

        if auto_mode and len(search_results) == 1:
            # Select single publication
            publication = search_results[0].publication
            logging.debug("The search returned a single match.")
            time.sleep(sleep_time)  # Prevent too many requests
        else:
            assert len(search_results) > 1
            # Let user select correct publication
            print("The search returned {} matches:".format(total_matches))
            if total_matches > max_search_results:
                print("Displaying only the first {} matches.".format(max_search_results))
            for i in range(len(search_results)):
                result = search_results[i]
                print("({})\t{}".format(i + 1, result.publication))
            # Let user select
            select = bibtex_dblp.io.get_user_number("Select the intended publication (0 to abort): ", 0, total_matches)

            if select == 0:
                missing_entries.append(search_string)
                continue
            publication = search_results[select - 1].publication

        result_dblp = bibtex_dblp.dblp_api.get_bibtex(publication.key, bib_format=bib_format)
        data = bibtex_dblp.database.parse_bibtex(result_dblp)
        assert len(data.entries) == 1

        # Update entries
        key = next(iter(data.entries))
        new_entries[entry_str] = data.entries[key]
        logging.debug("Updated entry for '{}'".format(data.entries))

    # Set new entries
    bib.entries = new_entries

    logging.info("The following entries were not found:")
    for m in missing_entries:
        logging.info("- {}".format(m))

    # Write to file
    bibtex_dblp.database.write_to_file(bib, outfile)
    logging.info("Written to {}".format(outfile))


if __name__ == "__main__":
    main()
