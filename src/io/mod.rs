use futures::{StreamExt, TryStreamExt};

use crate::{
    array::ops::as_arrow::AsArrow,
    datatypes::{BinaryArray, Utf8Array},
    error::{DaftError, DaftResult},
};

impl From<reqwest::Error> for DaftError {
    fn from(error: reqwest::Error) -> Self {
        DaftError::IoError(error.into())
    }
}

pub fn url_download<S: ToString, I: Iterator<Item = Option<S>>>(
    name: &str,
    urls: I,
    max_connections: usize,
    raise_error_on_failure: bool,
) -> DaftResult<BinaryArray> {
    if max_connections == 0 {
        return Err(DaftError::ValueError(
            "max_connections for url_download must be non-zero".into(),
        ));
    }
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    let fetches = futures::stream::iter(urls.enumerate().map(|(i, url)| {
        let owned_url = url.map(|s| s.to_string());

        tokio::spawn(async move {
            if owned_url.is_none() {
                return (i, None);
            }
            match reqwest::get(owned_url.unwrap())
                .await
                .and_then(|r| r.error_for_status())
            {
                Ok(response) => (i, Some(response.bytes().await)),
                Err(error) => (i, Some(Err(error))),
            }
        })
    }))
    .buffer_unordered(max_connections)
    .map(|f| match f {
        Ok((i, Some(Ok(bytes)))) => Ok((i, Some(bytes))),
        Ok((i, Some(Err(err)))) => match raise_error_on_failure {
            true => Err(err),
            false => {
                log::warn!("Error occurred during url_download at index: {i} {}", err);
                Ok((i, None))
            }
        },
        Ok((i, None)) => Ok((i, None)),
        Err(err) => panic!("Join error occured, this shouldnt happen: {}", err),
    });

    let mut results = rt.block_on(async move { fetches.try_collect::<Vec<_>>().await })?;

    results.sort_by_key(|k| k.0);
    let mut offsets: Vec<i64> = Vec::with_capacity(results.len() + 1);
    offsets.push(0);
    let mut valid = Vec::with_capacity(results.len());
    valid.reserve(results.len());
    let data = {
        let mut to_concat = Vec::with_capacity(results.len());

        for (i, b) in results.iter() {
            match b {
                Some(b) => {
                    to_concat.push(b.as_ref());
                    offsets.push(b.len() as i64 + offsets.last().unwrap());
                    valid.push(true);
                }
                None => {
                    offsets.push(*offsets.last().unwrap());
                    valid.push(false);
                }
            }
        }
        to_concat.concat()
    };
    BinaryArray::try_from((name, data, offsets))?.with_validity(valid.as_slice())
}

impl Utf8Array {
    pub fn url_download(
        &self,
        max_connections: usize,
        raise_error_on_failure: bool,
    ) -> DaftResult<BinaryArray> {
        let urls = self.as_arrow().iter();
        url_download(self.name(), urls, max_connections, raise_error_on_failure)
    }
}
