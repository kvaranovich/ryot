# Preferred edition language

Set `BOOKS_HARDCOVER_PREFERRED_LANGUAGE=ru` to display Russian edition titles,
covers and page counts when Hardcover supplies them for the same work.
An empty value preserves the original provider behavior.

The provider selects the most popular edition in that language, then prefers a
newer release, with edition ID as the deterministic final ordering. Missing
translations or covers retain work-level metadata. Search localization uses
one additional bounded request per result page and falls back to ordinary search
if that request fails.

The Hardcover work ID, ratings, reading history, private notes and public sync
identity do not change. Existing Ryot metadata needs a refresh after enabling
the setting. Descriptions remain work-level because Hardcover editions do not
expose their own description field. This feature does not generate translations.

Search text is passed as a GraphQL variable, fixing failures for titles that
contain quotes or backslashes.
