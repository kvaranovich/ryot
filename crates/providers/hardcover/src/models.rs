use anyhow::Result;
use chrono::NaiveDate;
use common_models::PersonSourceSpecifics;
use common_utils::PAGE_SIZE;
use nest_struct::nest_struct;
use reqwest::Client;
use rust_decimal::Decimal;
use serde::Deserialize;

pub static URL: &str = "https://api.hardcover.app/v1/graphql";

#[nest_struct]
#[derive(Debug, Deserialize)]
pub struct Response<T> {
    pub data: T,
}

#[nest_struct]
#[derive(Debug, Deserialize)]
pub struct Search {
    pub search: nest! {
        pub results: nest! {
            pub found: u64,
            pub hits: Vec<nest! { pub document: Item<String> }>,
        }
    },
}

#[nest_struct]
#[derive(Debug, Deserialize)]
pub struct Editions {
    pub editions: Vec<nest! { pub book_id: i64 }>,
}

#[derive(Debug, Deserialize)]
pub struct BooksByPk {
    pub books_by_pk: Item<i64>,
}

#[derive(Debug, Deserialize)]
pub struct LocalizedBooks {
    pub books: Vec<Item<i64>>,
}

#[derive(Debug, Deserialize)]
pub struct LocalizedEdition {
    pub title: Option<String>,
    pub pages: Option<i32>,
    pub image: Option<ImageOrLink>,
}

#[derive(Debug, Deserialize)]
pub struct AuthorsByPk {
    pub authors_by_pk: Item<i64>,
}

#[derive(Debug, Deserialize)]
pub struct PublishersByPk {
    pub publishers_by_pk: Item<i64>,
}

#[derive(Debug, Deserialize)]
pub struct SeriesByPk {
    pub series_by_pk: Item<i64>,
}

#[nest_struct]
#[derive(Debug, Deserialize)]
pub struct Item<TId> {
    pub id: TId,
    pub pages: Option<i32>,
    pub bio: Option<String>,
    pub name: Option<String>,
    pub slug: Option<String>,
    pub title: Option<String>,
    pub localized_editions: Option<Vec<LocalizedEdition>>,
    pub rating: Option<Decimal>,
    pub release_year: Option<i32>,
    pub compilation: Option<bool>,
    pub books_count: Option<usize>,
    pub image: Option<ImageOrLink>,
    pub description: Option<String>,
    pub born_date: Option<NaiveDate>,
    pub death_date: Option<NaiveDate>,
    pub links: Option<Vec<ImageOrLink>>,
    pub release_date: Option<NaiveDate>,
    pub images: Option<Vec<ImageOrLink>>,
    pub alternate_names: Option<Vec<String>>,
    pub editions: Option<Vec<nest! { pub book: Option<Item<TId>> }>>,
    pub cached_tags: Option<
        nest! {
          #[serde(rename = "Genre")]
          pub genre: Option<Vec<nest! { pub tag: String }>>
        },
    >,
    pub contributions: Option<
        Vec<
            nest! {
                pub author_id: Option<TId>,
                pub contribution: Option<String>,
                pub author: Option<nest! { pub name: String }>,
                pub book: Option<nest! { pub id: TId, pub title: String }>,
            },
        >,
    >,
    pub book_series: Option<
        Vec<
            nest! {
                pub book: Option<Item<TId>>,
                pub series: Option<nest! { pub id: TId, pub name: String }>
            },
        >,
    >,
}

#[nest_struct]
#[derive(Debug, Deserialize)]
pub struct ImageOrLink {
    pub url: Option<String>,
}

pub fn apply_localized_edition<T>(item: &mut Item<T>) -> bool {
    let edition = item.localized_editions.take().and_then(|editions| {
        editions.into_iter().find(|edition| {
            edition
                .title
                .as_ref()
                .is_some_and(|title| !title.trim().is_empty())
        })
    });
    let Some(edition) = edition else {
        return false;
    };
    item.title = edition.title;
    if edition.pages.is_some_and(|pages| pages > 0) {
        item.pages = edition.pages;
    }
    if edition
        .image
        .as_ref()
        .and_then(|image| image.url.as_ref())
        .is_some_and(|url| !url.trim().is_empty())
    {
        item.image = edition.image;
    }
    true
}

pub const LOCALIZED_BOOKS_QUERY: &str = r#"
query($ids: [Int!]!, $language: String!, $limit: Int!) {
  books(where: {id: {_in: $ids}}, limit: $limit) {
    id title image { url }
    localized_editions: editions(
      where: {language: {code2: {_eq: $language}}, title: {_is_null: false, _neq: ""}},
      order_by: [{users_count: desc_nulls_last}, {release_date: desc_nulls_last}, {id: asc}],
      limit: 1
    ) { title pages image { url } }
  }
}
"#;

pub fn search_request(query: &str, page: u64, query_type: &str) -> serde_json::Value {
    serde_json::json!({
        "query": "query($text:String!,$page:Int!,$take:Int!,$kind:String!){search(page:$page,per_page:$take,query:$text,query_type:$kind){results}}",
        "variables": {"text":query,"page":page,"take":PAGE_SIZE,"kind":query_type}
    })
}

#[cfg(test)]
mod localization_tests {
    use super::*;

    fn book(editions: serde_json::Value) -> Item<i64> {
        serde_json::from_value(serde_json::json!({
            "id": 337236,
            "title": "The Alchemist",
            "description": "Original work description",
            "pages": 200,
            "image": {"url":"https://covers.example/original.jpg"},
            "localized_editions": editions
        }))
        .unwrap()
    }

    #[test]
    fn localized_edition_preserves_work_identity_and_description() {
        let mut item = book(serde_json::json!([{
            "title":"Алхимик", "pages":224,
            "image":{"url":"https://covers.example/russian.jpg"}
        }]));
        assert!(apply_localized_edition(&mut item));
        assert_eq!(item.id, 337236);
        assert_eq!(item.title.as_deref(), Some("Алхимик"));
        assert_eq!(item.pages, Some(224));
        assert_eq!(
            item.image.unwrap().url.as_deref(),
            Some("https://covers.example/russian.jpg")
        );
        assert_eq!(
            item.description.as_deref(),
            Some("Original work description")
        );
    }

    #[test]
    fn unavailable_language_preserves_work_metadata() {
        let mut item = book(serde_json::json!([]));
        assert!(!apply_localized_edition(&mut item));
        assert_eq!(item.title.as_deref(), Some("The Alchemist"));
        assert_eq!(item.pages, Some(200));
    }

    #[test]
    fn missing_localized_cover_and_page_count_keep_original_values() {
        let mut item = book(serde_json::json!([{"title":"Алхимик","pages":null,"image":null}]));
        assert!(apply_localized_edition(&mut item));
        assert_eq!(
            item.image.unwrap().url.as_deref(),
            Some("https://covers.example/original.jpg")
        );
        assert_eq!(item.pages, Some(200));
    }

    #[test]
    fn blank_titles_do_not_replace_work_title() {
        let mut item = book(serde_json::json!([{"title":"  ","pages":0,"image":null}]));
        assert!(!apply_localized_edition(&mut item));
        assert_eq!(item.title.as_deref(), Some("The Alchemist"));
    }

    #[test]
    fn search_quotes_and_backslashes_are_bound_as_variables() {
        let text = "Клуб \"5 часов утра\" \\ example";
        let request = search_request(text, 3, "book");
        assert_eq!(request["variables"]["text"], text);
        assert_eq!(request["variables"]["page"], 3);
        assert!(!request["query"].as_str().unwrap().contains(text));
        let decoded: serde_json::Value =
            serde_json::from_str(&serde_json::to_string(&request).unwrap()).unwrap();
        assert_eq!(decoded["variables"]["text"], text);
    }
}

pub async fn get_search_response(
    query: &str,
    page: u64,
    query_type: &str,
    client: &Client,
) -> Result<SearchSearchResults> {
    let body = search_request(query, page, query_type);
    let data = client
        .post(URL)
        .json(&body)
        .send()
        .await?
        .json::<Response<Search>>()
        .await?;
    Ok(data.data.search.results)
}

pub fn query_type_from_specifics(source_specifics: &Option<PersonSourceSpecifics>) -> String {
    match source_specifics {
        Some(source_specifics) if source_specifics.is_hardcover_publisher.unwrap_or(false) => {
            "publisher".to_owned()
        }
        _ => "author".to_owned(),
    }
}

pub fn get_isbn_body(isbn_type: &str, isbn: &str) -> String {
    format!(
        r#"
query {{
  editions(where: {{ isbn_{isbn_type}: {{ _eq: "{isbn}" }} }}) {{
    book_id
  }}
}}
    "#
    )
}
