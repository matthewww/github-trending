create table repositories (
  id bigserial primary key,
  repo_name text not null,
  url text not null,
  description text,
  language text,
  stars integer,
  rank integer,
  collected_at timestamp default now()
);

create unique index idx_repo_date_unique on repositories(repo_name, (collected_at::date));
create index idx_repo_date on repositories(repo_name, collected_at);
create index idx_collected_at on repositories(collected_at);
create index idx_language on repositories(language);

create view today_trending as
  select repo_name, url, language, stars, rank
  from repositories
  where collected_at::date = current_date
  order by rank;
